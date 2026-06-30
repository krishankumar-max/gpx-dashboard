"""
FunnelService — goal-level conversion funnel computation.

Extracted from app.py: _build_funnel() + _funnel_time_to_complete().

Depends on the shared cache (same keys as AnalyticsService — no duplication)
and the storage layer (for raw parquet reads).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from backend.repositories.cache import CacheProvider

_CACHE_TTL_DATES: int = 30
_CACHE_TTL_CFG:   int = 60
_FUNNEL_COLS = ["cid", "goal", "time", "offerName", "partner"]


class FunnelService:
    """Builds goal-level conversion funnels from raw parquet data."""

    def __init__(self, cache: CacheProvider, storage) -> None:
        """
        Parameters
        ----------
        cache   : Shared CacheProvider (same instance as AnalyticsService).
        storage : StorageProvider from backend.storage.
        """
        self._cache   = cache
        self._storage = storage

    # ── Public interface ──────────────────────────────────────────────────────

    def build_funnel(
        self,
        offer_names: list[str],
        from_date:   dt.date,
        to_date:     dt.date,
        partners:    list[str],
    ) -> dict:
        """
        Unified funnel builder — Scenario A (configured) and Scenario B (fallback).

        Returns a dict ready to merge into an API response:
          {steps, total_users, final_count, overall_rate,
           total_dropoff, total_dropoff_pct, has_expected, mode}
        """
        _EMPTY = {
            "steps": [], "total_users": 0, "final_count": 0,
            "overall_rate": 0.0, "total_dropoff": 0, "total_dropoff_pct": 0.0,
            "has_expected": False, "mode": "fallback",
        }

        raw = self._storage.load_raw_range(from_date, to_date, columns=_FUNNEL_COLS)
        if raw.empty:
            return _EMPTY

        needed = {"offerName", "partner", "cid", "goal"}
        if not needed.issubset(raw.columns):
            return _EMPTY

        if offer_names:
            raw = raw[raw["offerName"].isin(offer_names)]
        if partners:
            raw = raw[raw["partner"].isin(partners)]
        if raw.empty:
            return _EMPTY

        # ── Look up expected funnel + payout map (single offer only) ────────────
        # Payout is read directly from each expected_funnel step's `payout` field.
        # Existing steps without `payout` default to 0.0 — no migration required.
        expected_steps: list[dict] = []
        payout_map:    dict[str, float] = {}   # goal_name → payout from expected funnel
        if len(offer_names) == 1:
            for cfg in self._get_game_configs():
                if cfg.get("offer_name") == offer_names[0]:
                    ef = cfg.get("expected_funnel") or []
                    if ef:
                        expected_steps = ef
                    for step in ef:
                        goal_name = (step.get("goal") or "").strip()
                        if not goal_name:
                            continue
                        raw_payout = step.get("payout")
                        try:
                            payout_map[goal_name] = float(raw_payout) if raw_payout is not None else 0.0
                        except (TypeError, ValueError):
                            payout_map[goal_name] = 0.0
                    break

        has_expected = bool(expected_steps)

        raw["goal"] = raw["goal"].fillna("").astype(str)
        raw["cid"]  = raw["cid"].fillna("").astype(str)

        goal_cid_sets: dict[str, frozenset] = {
            g: frozenset(grp["cid"])
            for g, grp in raw.groupby("goal", sort=False)
        }
        if not goal_cid_sets:
            return _EMPTY

        goal_counts: dict[str, int] = {g: len(s) for g, s in goal_cid_sets.items()}

        # ── Determine base goal for Phase 2 extension ─────────────────────────
        if has_expected and expected_steps:
            _p2_base_goal: str | None = str(expected_steps[0].get("goal", "")).strip() or None
        else:
            _all_g = set(goal_cid_sets.keys())
            if "1" in _all_g:
                _p2_base_goal = "1"
            else:
                _install_g = next((g for g in sorted(_all_g) if "install" in g.lower()), None)
                if _install_g:
                    _p2_base_goal = _install_g
                elif "session" in _all_g:
                    _p2_base_goal = "session"
                elif _all_g:
                    _p2_base_goal = max(_all_g, key=lambda g: goal_counts[g])
                else:
                    _p2_base_goal = None

        _p2_base_cids: frozenset = (
            goal_cid_sets.get(_p2_base_goal, frozenset()) if _p2_base_goal else frozenset()
        )

        raw_for_ttc = raw[["cid", "goal", "time"]].copy()

        # ── Phase 2: extend with future raw data ──────────────────────────────
        _ext_dates = [d for d in self._get_available_dates() if d > to_date]
        if _ext_dates and _p2_base_cids:
            _ext_frames: list[pd.DataFrame] = []
            for _d in _ext_dates:
                if not self._storage.raw_day_exists(_d):
                    continue
                try:
                    _df = self._storage.load_raw_day(_d, columns=_FUNNEL_COLS)
                except Exception:
                    continue
                if _df.empty:
                    continue
                if offer_names:
                    _df = _df[_df["offerName"].isin(offer_names)]
                if partners:
                    _df = _df[_df["partner"].isin(partners)]
                _df = _df[_df["cid"].isin(_p2_base_cids)]
                if not _df.empty:
                    _ext_frames.append(_df)

            if _ext_frames:
                _df_ext = pd.concat(_ext_frames, ignore_index=True)
                _df_ext["goal"] = _df_ext["goal"].fillna("").astype(str)
                _df_ext["cid"]  = _df_ext["cid"].fillna("").astype(str)
                for _g, _grp in _df_ext.groupby("goal", sort=False):
                    _existing = goal_cid_sets.get(_g, frozenset())
                    goal_cid_sets[_g] = _existing | frozenset(_grp["cid"])
                raw_for_ttc = pd.concat(
                    [raw_for_ttc, _df_ext[["cid", "goal", "time"]]],
                    ignore_index=True,
                )

        # ── Build funnel steps ─────────────────────────────────────────────────
        if has_expected:
            funnel_steps = self._scenario_a(expected_steps, goal_cid_sets)
        else:
            funnel_steps = self._scenario_b(goal_cid_sets, goal_counts)

        if not funnel_steps:
            return _EMPTY

        # ── Time-to-complete ──────────────────────────────────────────────────
        step_names = [s["goal"] for s in funnel_steps]
        ttc = self._funnel_time_to_complete(raw_for_ttc, step_names, _p2_base_cids)
        for s in funnel_steps:
            s["time_to_complete"] = ttc.get(s["goal"])

        # ── Payout + total cost per step ──────────────────────────────────────
        for s in funnel_steps:
            bid = payout_map.get(s["goal"])
            s["payout"]     = round(bid, 4) if bid is not None else None
            s["total_cost"] = round(s["count"] * bid, 2) if bid is not None else None

        total_users   = funnel_steps[0]["count"]
        final_count   = funnel_steps[-1]["count"]
        total_dropoff = total_users - final_count
        return {
            "steps":             funnel_steps,
            "total_users":       total_users,
            "final_count":       final_count,
            "overall_rate":      round(final_count / total_users * 100, 2) if total_users else 0.0,
            "total_dropoff":     total_dropoff,
            "total_dropoff_pct": round(total_dropoff / total_users * 100, 2) if total_users else 0.0,
            "has_expected":      has_expected,
            "mode":              "configured" if has_expected else "fallback",
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _scenario_a(self, expected_steps: list, goal_cid_sets: dict) -> list[dict]:
        """Configured funnel — true cohort through expected steps."""
        config_steps: list[tuple[str, float, str | None]] = []
        for ef_step in expected_steps:
            goal_name = str(ef_step.get("goal", "")).strip()
            if not goal_name:
                continue
            expected_pct  = float(ef_step.get("pct") or 0)
            expected_time = self._fmt_expected_time(ef_step.get("time_val"), ef_step.get("time_unit", "Days"))
            config_steps.append((goal_name, expected_pct, expected_time))

        if not config_steps:
            return []

        base_goal_name = config_steps[0][0]
        base_cids      = goal_cid_sets.get(base_goal_name, frozenset())
        base_count     = len(base_cids) or 1

        steps = []
        for i, (goal_name, exp_pct, exp_time) in enumerate(config_steps):
            cnt = len(base_cids) if i == 0 else len(base_cids & goal_cid_sets.get(goal_name, frozenset()))
            actual_pct    = round(cnt / base_count * 100, 2)
            deviation_pct = round(actual_pct - exp_pct, 2)
            steps.append({
                "step": i + 1, "goal": goal_name, "count": cnt,
                "funnel_pct":    actual_pct,  "time_to_complete": None,
                "expected_pct":  exp_pct,     "deviation_pct":    deviation_pct,
                "expected_time": exp_time,
            })
        return steps

    def _scenario_b(self, goal_cid_sets: dict, goal_counts: dict) -> list[dict]:
        """Fallback funnel — auto-select base, all goals, true cohort."""
        all_goals = set(goal_cid_sets.keys())
        if "1" in all_goals:
            base_goal: str | None = "1"
        else:
            install_g = next((g for g in sorted(all_goals) if "install" in g.lower()), None)
            if install_g:
                base_goal = install_g
            elif "session" in all_goals:
                base_goal = "session"
            elif all_goals:
                base_goal = max(all_goals, key=lambda g: goal_counts[g])
            else:
                base_goal = None

        if base_goal is None:
            return []

        base_cids  = goal_cid_sets.get(base_goal, frozenset())
        base_count = len(base_cids) or 1

        others = sorted(
            [(g, len(base_cids & goal_cid_sets.get(g, frozenset())))
             for g in all_goals if g != base_goal],
            key=lambda x: -x[1],
        )
        ordered = [(base_goal, len(base_cids))] + others

        return [
            {
                "step": i + 1, "goal": goal, "count": cnt,
                "funnel_pct":    round(cnt / base_count * 100, 2),
                "time_to_complete": None,
                "expected_pct":  None, "deviation_pct": None, "expected_time": None,
            }
            for i, (goal, cnt) in enumerate(ordered)
        ]

    @staticmethod
    def _fmt_expected_time(time_val, time_unit: str) -> str | None:
        if not time_val and time_val != 0:
            return None
        try:
            val = float(time_val)
        except (ValueError, TypeError):
            return None
        if val <= 0:
            return None
        unit = str(time_unit or "Days").lower()
        if "minute" in unit:
            return f"{int(val)}m"
        elif "hour" in unit:
            return f"{int(val)}h"
        return f"{int(val)}d"

    @staticmethod
    def _funnel_time_to_complete(
        raw_df:         pd.DataFrame,
        step_names:     list[str],
        base_cids:      frozenset,
    ) -> dict[str, str | None]:
        """
        Median time-to-complete per step (from base step timestamp).
        Returns {goal_name: formatted_duration_string | None}.
        """
        from backend.services.analytics import AnalyticsService

        if raw_df.empty or "time" not in raw_df.columns or not base_cids:
            return {s: None for s in step_names}

        df = raw_df.copy()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        df = df.dropna(subset=["time"])

        base_step = step_names[0] if step_names else None
        if not base_step:
            return {s: None for s in step_names}

        base_df      = df[(df["goal"] == base_step) & (df["cid"].isin(base_cids))]
        base_ts_dict = base_df.groupby("cid")["time"].min().to_dict()

        result: dict[str, str | None] = {}
        for step in step_names:
            if step == base_step:
                result[step] = None
                continue
            step_df = df[(df["goal"] == step) & (df["cid"].isin(base_cids))]
            if step_df.empty:
                result[step] = None
                continue

            deltas = []
            for cid, grp in step_df.groupby("cid"):
                base_ts = base_ts_dict.get(cid)
                if base_ts is None:
                    continue
                earliest = grp["time"].min()
                delta    = (earliest - base_ts).total_seconds()
                if delta >= 0:
                    deltas.append(delta)

            if not deltas:
                result[step] = None
                continue

            deltas.sort()
            median_sec = deltas[len(deltas) // 2]
            result[step] = AnalyticsService.fmt_duration(int(median_sec))

        return result

    def _get_game_configs(self) -> list:
        """Read game configs from shared cache (same TTL and key as AnalyticsService).

        The "gcfg" key must always contain only non-pending (fully configured)
        records, matching what GameConfigService.list() / AnalyticsService writes.
        Using get_all_raw() here would poison the shared key with pending stubs,
        causing AnalyticsService to treat unconfigured offers as configured on the
        next cache hit.
        """
        configs = self._cache.get("gcfg")
        if configs is None:
            # Fallback: re-build from storage (rare — only if cache is cold)
            from backend.repositories.factory import RepositoryFactory
            from backend.config import REPO_BACKEND
            try:
                from backend.services.game_config import is_configured as _is_configured
                repo = RepositoryFactory.create_game_config_repo(REPO_BACKEND)
                # Use the canonical predicate — single definition lives in GameConfigService
                configs = [r for r in repo.get_all_raw() if _is_configured(r)]
                self._cache.set("gcfg", configs, ttl=_CACHE_TTL_CFG)
            except Exception:
                configs = []
        return configs

    def _get_available_dates(self) -> list:
        """Read available dates from shared cache."""
        dates = self._cache.get("dates")
        if dates is None:
            dates = self._storage.available_dates()
            self._cache.set("dates", dates, ttl=_CACHE_TTL_DATES)
        return dates
