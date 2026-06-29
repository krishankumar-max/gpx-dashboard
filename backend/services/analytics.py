"""
AnalyticsService — all analytics computation, caching, and data enrichment.

Every analytics API endpoint has a corresponding method here.
Routes are thin: parse request → call method → return jsonify(result).

Business rules for revenue, margins, filtering, and KPI classification live here.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
from typing import TYPE_CHECKING

import pandas as pd

from backend.aggregator import load_summary
from backend.repositories.cache import CacheProvider
from backend.storage import available_dates as _storage_available_dates
from backend.storage import load_date_range as _storage_load_date_range
from backend.utils import ist_today

if TYPE_CHECKING:
    from backend.services.funnel import FunnelService

_IST = "Asia/Kolkata"
_IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))

_CACHE_TTL_SUMMARY: int = 300
_CACHE_TTL_DATES:   int = 30
_CACHE_TTL_CFG:     int = 60


class AnalyticsService:
    """
    All analytics computation.

    Parameters
    ----------
    cache           : Shared CacheProvider.
    game_config_svc : GameConfigService (for configured offer lists).
    publisher_svc   : PublisherService (for publisher KPI page).
    funnel_svc      : FunnelService (for offer/publisher profile endpoints).
    """

    def __init__(
        self,
        cache,
        game_config_svc,
        publisher_svc,
        funnel_svc: "FunnelService",
    ) -> None:
        self._cache           = cache
        self._game_config_svc = game_config_svc
        self._publisher_svc   = publisher_svc
        self._funnel_svc      = funnel_svc

    # ══════════════════════════════════════════════════════════════════════════
    # Cache-backed data accessors
    # ══════════════════════════════════════════════════════════════════════════

    def get_summary(self) -> pd.DataFrame:
        df = self._cache.get("df")
        if df is None:
            df = load_summary()
            self._cache.set("df", df, ttl=_CACHE_TTL_SUMMARY)
            self._cache.evict("edf")
        return df

    def get_available_dates(self) -> list:
        dates = self._cache.get("dates")
        if dates is None:
            dates = _storage_available_dates()
            self._cache.set("dates", dates, ttl=_CACHE_TTL_DATES)
        return dates

    def get_game_configs(self) -> list:
        configs = self._cache.get("gcfg")
        if configs is None:
            configs = self._game_config_svc.list()
            self._cache.set("gcfg", configs, ttl=_CACHE_TTL_CFG)
        return configs

    def get_offer_id_map(self) -> dict[str, str]:
        """Return {offerName: offer_id} built from game configs."""
        cached = self._cache.get("oid_map")
        if cached is not None:
            return cached
        result: dict[str, str] = {}
        for cfg in self.get_game_configs():
            name = str(cfg.get("offer_name", "")).strip()
            oid  = str(cfg.get("offer_id",   "")).strip()
            if name and oid:
                result[name] = oid
        self._cache.set("oid_map", result, ttl=_CACHE_TTL_CFG)
        return result

    def get_configured_offer_ids(self) -> frozenset[str]:
        """
        Return offer_ids for game configs that are actively configured.

        Excludes records with campaign_status == "pending" — these are
        auto-seeded stubs that have not yet been reviewed by an admin.
        Pending offers are intentionally hidden from all dashboard views.
        """
        return frozenset(
            str(cfg.get("offer_id", "")).strip()
            for cfg in self.get_game_configs()
            if str(cfg.get("offer_id", "")).strip()
            and cfg.get("campaign_status") != "pending"
        )

    def get_configured_offer_names(self) -> frozenset[str]:
        oid_map  = self.get_offer_id_map()
        conf_ids = self.get_configured_offer_ids()
        return frozenset(name for name, oid in oid_map.items() if oid in conf_ids)

    def _build_config_revenue_map(self) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for cfg in self.get_game_configs():
            oid = str(cfg.get("offer_id", "")).strip()
            pgs = cfg.get("payable_goals") or []
            if not oid or not pgs:
                continue
            goal_bids: dict[str, float] = {}
            for pg in pgs:
                if not isinstance(pg, dict):
                    continue
                goal = str(pg.get("name", "")).strip()
                try:
                    bid = float(pg.get("bid") or 0)
                except (ValueError, TypeError):
                    bid = 0.0
                if goal and bid > 0:
                    goal_bids[goal] = bid
            if goal_bids:
                result[oid] = goal_bids
        return result

    def get_enriched_summary(self) -> pd.DataFrame:
        """
        Return daily_summary filtered to configured offers, with config revenue applied.
        Cached at _CACHE_TTL_CFG (60 s).
        """
        cached = self._cache.get("edf")
        if cached is not None:
            return cached

        df = self.get_summary().copy()

        oid_map = self.get_offer_id_map()
        cfg_map = self._build_config_revenue_map()

        df["offer_id"] = df["offerName"].map(oid_map).fillna("").astype(str)
        df["sapphyre_revenue"] = df["revenue"].astype(float)

        _bid_lookup: dict[tuple, float] = {}
        for _oid, _goal_bids in cfg_map.items():
            for _goal, _bid in _goal_bids.items():
                _bid_lookup[(_oid, _goal)] = _bid

        if _bid_lookup:
            _keys = list(zip(df["offer_id"], df["goal"].astype(str)))
            _bids = pd.Series(
                [_bid_lookup.get(k, 0.0) for k in _keys], index=df.index, dtype=float
            )
            df["config_revenue"] = (df["conversions"].astype(float) * _bids).round(4)
        else:
            df["config_revenue"] = 0.0

        _configured_ids: frozenset = frozenset(cfg_map.keys())
        df["revenue_source"] = df["offer_id"].map(
            lambda oid: "config" if oid in _configured_ids else "sapphyre"
        )
        _config_mask = df["revenue_source"] == "config"
        df["revenue"] = df["sapphyre_revenue"]
        df.loc[_config_mask, "revenue"] = df.loc[_config_mask, "config_revenue"]

        # Always filter to configured offers. If no game configs exist, returns
        # an empty DataFrame — dashboards must not display raw/unconfigured offers.
        _conf_ids = self.get_configured_offer_ids()
        df = df[df["offer_id"].isin(_conf_ids)]

        self._cache.set("edf", df, ttl=_CACHE_TTL_CFG)
        return df

    # ══════════════════════════════════════════════════════════════════════════
    # Pure utility / static helpers
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def apply_ist(df: pd.DataFrame) -> pd.DataFrame:
        if "time" not in df.columns:
            return df
        df = df.copy()
        df["time"] = (
            pd.to_datetime(df["time"], utc=True, errors="coerce")
            .dt.tz_convert(_IST)
            .dt.strftime("%Y-%m-%d %H:%M:%S")
        )
        return df

    @staticmethod
    def slice_summary(
        df: pd.DataFrame,
        from_date: dt.date | None,
        to_date:   dt.date | None,
        partners:  list[str],
        offers:    list[str],
        goals:     list[str],
    ) -> pd.DataFrame:
        if df.empty:
            return df
        if from_date:
            df = df[df["date"] >= from_date]
        if to_date:
            df = df[df["date"] <= to_date]
        if partners:
            df = df[df["partner"].isin(partners)]
        if offers:
            df = df[df["offerName"].isin(offers)]
        if goals:
            df = df[df["goal"].isin(goals)]
        return df

    @staticmethod
    def offer_metrics(df: pd.DataFrame) -> dict:
        if df.empty:
            return dict(revenue=0, cost=0, profit=0, margin_pct=0,
                        conversions=0, valid_conversions=0, conversion_rate=0,
                        active_offers=0, active_publishers=0, installs=0, events=0)
        revenue = float(df["revenue"].sum())
        cost    = float(df["payout"].sum())
        profit  = revenue - cost
        margin_pct  = round(profit / revenue * 100, 2) if revenue else 0.0
        conversions = int(df["conversions"].sum())
        valid_conv  = int(df["valid_conversions"].sum())
        conv_rate   = round(valid_conv / conversions * 100, 2) if conversions else 0.0
        installs = int(df["unique_installs"].sum())
        return dict(
            revenue=round(revenue, 2), cost=round(cost, 2),
            profit=round(profit, 2),   margin_pct=margin_pct,
            conversions=conversions,   valid_conversions=valid_conv,
            conversion_rate=conv_rate,
            active_offers=int(df["offerName"].nunique()),
            active_publishers=int(df["partner"].nunique()),
            installs=installs, events=conversions - installs,
        )

    @staticmethod
    def pct_change(curr: float, prev: float) -> float | None:
        if prev == 0:
            return None
        return round((curr - prev) / prev * 100, 1)

    @staticmethod
    def fmt_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            m, s = divmod(seconds, 60)
            return f"{m}m {s}s"
        if seconds < 86400:
            h, rem = divmod(seconds, 3600)
            return f"{h}h {rem // 60}m"
        d, rem = divmod(seconds, 86400)
        return f"{d}d {rem // 3600}h"

    @staticmethod
    def month_week_range(date: dt.date) -> tuple[dt.date, dt.date]:
        d = date.day
        last = _cal.monthrange(date.year, date.month)[1]
        if d <= 7:  return date.replace(day=1),  date.replace(day=min(7,  last))
        if d <= 14: return date.replace(day=8),  date.replace(day=min(14, last))
        if d <= 21: return date.replace(day=15), date.replace(day=min(21, last))
        return           date.replace(day=22), date.replace(day=last)

    @staticmethod
    def prev_month_week_range(date: dt.date) -> tuple[dt.date, dt.date]:
        d = date.day
        last = _cal.monthrange(date.year, date.month)[1]
        if d <= 7:
            pm_last     = date.replace(day=1) - dt.timedelta(days=1)
            pm_last_day = _cal.monthrange(pm_last.year, pm_last.month)[1]
            return pm_last.replace(day=22), pm_last.replace(day=pm_last_day)
        if d <= 14: return date.replace(day=1),  date.replace(day=7)
        if d <= 21: return date.replace(day=8),  date.replace(day=14)
        return           date.replace(day=15), date.replace(day=21)

    # ══════════════════════════════════════════════════════════════════════════
    # Status / filters
    # ══════════════════════════════════════════════════════════════════════════

    def status(self) -> dict:
        dates = self.get_available_dates()
        return {
            "has_data":      bool(dates),
            "available_days": len(dates),
            "min_date":      dates[0].isoformat() if dates else None,
            "max_date":      dates[-1].isoformat() if dates else None,
        }

    def filters(
        self,
        from_date: dt.date | None,
        to_date:   dt.date | None,
        partners:  list[str],
        offers:    list[str],
        goals:     list[str],
    ) -> dict:
        """
        Return cascading filter options.

        Cascade order: date → partners → offers → goals.
        Each tier is filtered by all upstream selections so that the dropdown
        for offers only shows offers that exist under the selected partners,
        and goals only show under the selected partners+offers.
        """
        df = self.get_enriched_summary()
        if df.empty:
            return {"partners": [], "offers": [], "goals": []}

        # Date base — common to all tiers
        base = df
        if from_date:
            base = base[base["date"] >= from_date]
        if to_date:
            base = base[base["date"] <= to_date]

        all_partners = sorted(base["partner"].dropna().unique().tolist())

        # Offers depend on selected partners
        p_base    = base[base["partner"].isin(partners)] if partners else base
        all_offers = sorted(p_base["offerName"].dropna().unique().tolist())

        # Goals depend on selected partners + offers
        o_base    = p_base[p_base["offerName"].isin(offers)] if offers else p_base
        all_goals = sorted(o_base["goal"].dropna().unique().tolist())

        return {"partners": all_partners, "offers": all_offers, "goals": all_goals}

    # ══════════════════════════════════════════════════════════════════════════
    # Raw data / export
    # ══════════════════════════════════════════════════════════════════════════

    def raw_data(
        self,
        from_date: dt.date,
        to_date:   dt.date,
        partners:  list[str],
        offers:    list[str],
        goals:     list[str],
        search:    str,
        page:      int,
        per_page:  int,
    ) -> dict:
        conf_names = self.get_configured_offer_names()
        raw = _storage_load_date_range(from_date, to_date)
        raw = self.apply_ist(raw)

        if raw.empty:
            return {"rows": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

        if partners and "partner" in raw.columns:
            raw = raw[raw["partner"].isin(partners)]
        if offers and "offerName" in raw.columns:
            raw = raw[raw["offerName"].isin(offers)]
        elif "offerName" in raw.columns:
            # No explicit offer filter — restrict to configured offers only.
            # Empty conf_names (no game configs) → empty result, by design.
            raw = raw[raw["offerName"].isin(conf_names)]
        if goals and "goal" in raw.columns:
            raw = raw[raw["goal"].isin(goals)]

        if search and "offerName" in raw.columns:
            mask = raw["offerName"].str.contains(search, case=False, na=False)
            for col in ("partner", "goal", "country"):
                if col in raw.columns:
                    mask |= raw[col].astype(str).str.contains(search, case=False, na=False)
            raw = raw[mask]

        raw = raw.sort_values("time", ascending=False) if "time" in raw.columns else raw
        total = len(raw)
        pages = (total + per_page - 1) // per_page if per_page > 0 else 1
        start = (page - 1) * per_page
        page_df = raw.iloc[start: start + per_page]

        rows = page_df.where(pd.notnull(page_df), None).to_dict(orient="records")
        return {"rows": rows, "total": total, "page": page, "per_page": per_page, "pages": pages}

    def export_csv(
        self,
        from_date: dt.date,
        to_date:   dt.date,
        partners:  list[str],
        offers:    list[str],
        goals:     list[str],
        search:    str,
    ) -> tuple[str, str]:
        """Returns (csv_content, filename)."""
        conf_names = self.get_configured_offer_names()
        raw = _storage_load_date_range(from_date, to_date)
        raw = self.apply_ist(raw)

        if not raw.empty:
            if partners and "partner" in raw.columns:
                raw = raw[raw["partner"].isin(partners)]
            if offers and "offerName" in raw.columns:
                raw = raw[raw["offerName"].isin(offers)]
            elif "offerName" in raw.columns:
                # No explicit offer filter — restrict to configured offers only.
                raw = raw[raw["offerName"].isin(conf_names)]
            if goals and "goal" in raw.columns:
                raw = raw[raw["goal"].isin(goals)]
            if search:
                mask = pd.Series(False, index=raw.index)
                for col in ("offerName", "partner", "goal", "country"):
                    if col in raw.columns:
                        mask |= raw[col].astype(str).str.contains(search, case=False, na=False)
                raw = raw[mask]
            if "time" in raw.columns:
                raw = raw.sort_values("time", ascending=False)

        filename = f"gpx_export_{from_date}_{to_date}.csv"
        return raw.to_csv(index=False), filename

    # ══════════════════════════════════════════════════════════════════════════
    # Overview endpoints
    # ══════════════════════════════════════════════════════════════════════════

    def overview_kpis(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return dict(revenue=0, cost=0, profit=0, margin_pct=0,
                        active_offers=0, active_publishers=0, installs=0)
        revenue = float(filtered["revenue"].sum())
        cost    = float(filtered["payout"].sum())
        profit  = revenue - cost
        margin_pct = round(profit / revenue * 100, 2) if revenue else 0.0
        install_rows      = filtered[filtered["unique_installs"] > 0]
        installs          = int(filtered["unique_installs"].sum())
        active_offers     = int(install_rows["offerName"].nunique())
        active_publishers = int(install_rows["partner"].nunique())
        return dict(
            revenue=round(revenue, 2), cost=round(cost, 2),
            profit=round(profit, 2),   margin_pct=margin_pct,
            active_offers=active_offers, active_publishers=active_publishers,
            installs=installs,
        )

    def overview_comparisons(
        self,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        """
        Return three period comparisons for the Overview page.

        Keys match what the frontend expects exactly:
          today_vs_yesterday, week_vs_prev_week, mtd_vs_last_month, week_labels
        """
        df    = self.get_enriched_summary()
        today = ist_today()
        yest  = today - dt.timedelta(days=1)

        def _m(from_d, to_d):
            d = self.slice_summary(df, from_d, to_d, partners, offers, goals)
            if d.empty:
                return dict(revenue=0, cost=0, profit=0, conversions=0, installs=0)
            rev  = round(float(d["revenue"].sum()), 2)
            cost = round(float(d["payout"].sum()), 2)
            return dict(revenue=rev, cost=cost,
                        profit=round(rev - cost, 2),
                        conversions=int(d["conversions"].sum()),
                        installs=int(d["unique_installs"].sum()))

        def _cmp(curr, prev):
            out = {}
            for k in ("revenue", "cost", "profit", "conversions", "installs"):
                out[k] = dict(current=curr[k], previous=prev[k],
                              change=round(curr[k] - prev[k], 2),
                              pct_change=self.pct_change(curr[k], prev[k]))
            return out

        curr_w_start, curr_w_end = self.month_week_range(today)
        curr_w_end = min(curr_w_end, today)
        prev_w_start, prev_w_end = self.prev_month_week_range(today)

        month_start  = today.replace(day=1)
        prev_m_end   = month_start - dt.timedelta(days=1)
        prev_m_start = prev_m_end.replace(day=1)

        return {
            "today_vs_yesterday": _cmp(_m(today, today), _m(yest, yest)),
            "week_vs_prev_week":  _cmp(_m(curr_w_start, curr_w_end), _m(prev_w_start, prev_w_end)),
            "mtd_vs_last_month":  _cmp(_m(month_start, today), _m(prev_m_start, prev_m_end)),
            "week_labels": {
                "current":  f"{curr_w_start.strftime('%-d %b')} – {curr_w_end.strftime('%-d %b')}",
                "previous": f"{prev_w_start.strftime('%-d %b')} – {prev_w_end.strftime('%-d %b')}",
            },
        }

    def overview_trend(
        self,
        from_date: dt.date | None, to_date: dt.date | None,
        days: int,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> list:
        df = self.get_enriched_summary()
        if days > 0:
            to_date   = ist_today()
            from_date = to_date - dt.timedelta(days=days - 1)

        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return []

        daily = (
            filtered.groupby("date", as_index=False)
            .agg(revenue=("revenue", "sum"), payout=("payout", "sum"),
                 installs=("unique_installs", "sum"))
        )
        daily["installs"]   = daily["installs"].astype(int)
        daily["profit"]     = (daily["revenue"] - daily["payout"]).round(2)
        daily["margin_pct"] = (
            daily["profit"] / daily["revenue"].replace(0, float("nan")) * 100
        ).round(2).fillna(0)
        daily["revenue"]    = daily["revenue"].round(2)
        daily["payout"]     = daily["payout"].round(2)
        daily               = daily.rename(columns={"payout": "cost"})
        daily["date"]       = daily["date"].astype(str)
        return daily.sort_values("date").to_dict(orient="records")

    def overview_leaderboards(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return {"publishers": [], "offers": []}

        def _top10(group_col, label_col):
            stats = (
                filtered.groupby(group_col, as_index=False)
                .agg(revenue=("revenue", "sum"), payout=("payout", "sum"))
            )
            stats["profit"]     = (stats["revenue"] - stats["payout"]).round(2)
            stats["margin_pct"] = (
                stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100
            ).round(2).fillna(0)
            stats["revenue"] = stats["revenue"].round(2)
            stats["payout"]  = stats["payout"].round(2)
            stats = stats.rename(columns={group_col: label_col})
            return (
                stats.sort_values(["revenue", "margin_pct"], ascending=[False, False])
                .head(10).to_dict(orient="records")
            )

        return {
            "publishers": _top10("partner",   "partner"),
            "offers":     _top10("offerName", "offerName"),
        }

    def overview_alerts(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        alerts: list[dict] = []

        if not filtered.empty:
            stats = (
                filtered.groupby("offerName", as_index=False)
                .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                     conversions=("conversions","sum"))
            )
            stats["profit"]     = stats["revenue"] - stats["payout"]
            stats["margin_pct"] = (
                stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100
            ).round(2).fillna(0)

            for _, r in stats.iterrows():
                name = r["offerName"]; mp = float(r["margin_pct"])
                if float(r["profit"]) < 0:
                    alerts.append(dict(type="negative_margin", severity="critical",
                        offer=name, margin_pct=round(mp,1),
                        message=f"{name}: Negative margin ({mp:.1f}%)"))
                elif mp < 5:
                    alerts.append(dict(type="margin_below_5", severity="critical",
                        offer=name, margin_pct=round(mp,1),
                        message=f"{name}: Margin critically low ({mp:.1f}%)"))
                elif mp < 20:
                    alerts.append(dict(type="margin_below_20", severity="warning",
                        offer=name, margin_pct=round(mp,1),
                        message=f"{name}: Margin below 20% ({mp:.1f}%)"))

        today = ist_today()
        yest  = today - dt.timedelta(days=1)
        day_b = yest  - dt.timedelta(days=1)
        y_df  = self.slice_summary(df, yest,  yest,  partners, offers, goals)
        p_df  = self.slice_summary(df, day_b, day_b, partners, offers, goals)
        y_rev  = float(y_df["revenue"].sum()) if not y_df.empty else 0
        p_rev  = float(p_df["revenue"].sum()) if not p_df.empty else 0
        y_conv = int(y_df["conversions"].sum()) if not y_df.empty else 0
        p_conv = int(p_df["conversions"].sum()) if not p_df.empty else 0

        if p_rev > 0 and y_rev < p_rev * 0.8:
            drop = round((p_rev - y_rev) / p_rev * 100, 1)
            alerts.append(dict(type="revenue_drop", severity="warning", offer=None,
                message=f"Revenue dropped {drop}% yesterday vs day before"))
        if p_conv > 0 and y_conv < p_conv * 0.7:
            drop = round((p_conv - y_conv) / p_conv * 100, 1)
            alerts.append(dict(type="traffic_drop", severity="warning", offer=None,
                message=f"Traffic dropped {drop}% yesterday vs day before"))

        return {"alerts": alerts, "count": len(alerts)}

    # ══════════════════════════════════════════════════════════════════════════
    # Health digest
    # ══════════════════════════════════════════════════════════════════════════

    def health_digest(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df    = self.get_enriched_summary()
        today = ist_today()
        yest  = today - dt.timedelta(days=1)
        day_b = yest  - dt.timedelta(days=1)

        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        y_df     = self.slice_summary(df, yest,  yest,  partners, offers, goals)
        p_df     = self.slice_summary(df, day_b, day_b, partners, offers, goals)

        MIN_REV  = 100.0
        MIN_INST = 10

        if not filtered.empty:
            ofr = (
                filtered.groupby("offerName", as_index=False)
                .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                     installs=("unique_installs","sum"),
                     conversions=("conversions","sum"),
                     valid_conversions=("valid_conversions","sum"))
            )
            ofr["profit"]     = ofr["revenue"] - ofr["payout"]
            ofr["margin_pct"] = (ofr["profit"] / ofr["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
            ofr["conv_rate"]  = (ofr["valid_conversions"] / ofr["conversions"].replace(0, float("nan")) * 100).round(2).fillna(0)
            pub = (
                filtered.groupby("partner", as_index=False)
                .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                     installs=("unique_installs","sum"), active_offers=("offerName","nunique"))
            )
            pub["profit"]     = pub["revenue"] - pub["payout"]
            pub["margin_pct"] = (pub["profit"] / pub["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        else:
            ofr = pd.DataFrame(); pub = pd.DataFrame()

        _empty_dod = pd.DataFrame(columns=[
            "offerName","revenue_y","installs_y","conv_y","valid_y",
            "revenue_p","installs_p","conv_p","valid_p",
        ])
        if not y_df.empty:
            y_off = y_df.groupby("offerName", as_index=False).agg(
                revenue_y=("revenue","sum"), installs_y=("unique_installs","sum"),
                conv_y=("conversions","sum"), valid_y=("valid_conversions","sum"))
        else:
            y_off = _empty_dod[["offerName","revenue_y","installs_y","conv_y","valid_y"]].copy()
        if not p_df.empty:
            p_off = p_df.groupby("offerName", as_index=False).agg(
                revenue_p=("revenue","sum"), installs_p=("unique_installs","sum"),
                conv_p=("conversions","sum"), valid_p=("valid_conversions","sum"))
        else:
            p_off = _empty_dod[["offerName","revenue_p","installs_p","conv_p","valid_p"]].copy()
        dod = (y_off.merge(p_off, on="offerName", how="outer").fillna(0)
               if (not y_off.empty or not p_off.empty) else _empty_dod)

        def _status(mp: float) -> str:
            if mp < 0:  return "at_risk"
            if mp < 20: return "watchlist"
            return "healthy"

        # Revenue at risk
        risk_items: list[dict] = []
        if not ofr.empty:
            dod_rev: dict = {}
            if not dod.empty:
                for _, dr in dod.iterrows():
                    dod_rev[dr["offerName"]] = (float(dr["revenue_p"]), float(dr["revenue_y"]))
            for _, r in ofr.iterrows():
                rev = float(r["revenue"]); mp = float(r["margin_pct"])
                if rev < MIN_REV: continue
                reasons: list[str] = []; sev = "warning"
                if float(r["profit"]) < 0:
                    reasons.append(f"Negative margin ({mp:.1f}%)"); sev = "critical"
                elif mp < 5:
                    reasons.append(f"Critical margin ({mp:.1f}%)"); sev = "critical"
                elif mp < 15:
                    reasons.append(f"Low margin ({mp:.1f}%)")
                if r["offerName"] in dod_rev:
                    p_rev, y_rev = dod_rev[r["offerName"]]
                    if p_rev >= MIN_REV and y_rev < p_rev * 0.6:
                        drop = round((p_rev - y_rev) / p_rev * 100, 1)
                        reasons.append(f"Revenue dropped {drop:.0f}% yesterday")
                if reasons:
                    risk_items.append(dict(
                        offerName=r["offerName"], revenue=round(rev, 2),
                        profit=round(float(r["profit"]), 2), margin_pct=round(mp, 2),
                        installs=int(r["installs"]), reasons=reasons, severity=sev))
        risk_items.sort(key=lambda x: (0 if x["severity"] == "critical" else 1, -x["revenue"]))

        # Scale opportunities
        risk_names = {x["offerName"] for x in risk_items}
        scale_items: list[dict] = []
        if not ofr.empty:
            for _, r in ofr.iterrows():
                rev = float(r["revenue"]); mp = float(r["margin_pct"])
                if mp <= 30 or rev < MIN_REV * 5 or r["offerName"] in risk_names: continue
                confidence = "high" if mp > 50 and rev >= MIN_REV * 30 else "medium"
                scale_items.append(dict(offerName=r["offerName"], revenue=round(rev, 2),
                    profit=round(float(r["profit"]), 2), margin_pct=round(mp, 2),
                    installs=int(r["installs"]), confidence=confidence))
        scale_items.sort(key=lambda x: x["revenue"] * x["margin_pct"] / 100, reverse=True)

        # Publisher health
        pub_health: list[dict] = []
        if not pub.empty:
            for _, r in pub.iterrows():
                mp = float(r["margin_pct"]); rev = float(r["revenue"])
                pub_health.append(dict(partner=r["partner"], revenue=round(rev, 2),
                    profit=round(float(r["profit"]), 2), margin_pct=round(mp, 2),
                    installs=int(r["installs"]), active_offers=int(r["active_offers"]),
                    status=_status(mp)))
        pub_health.sort(key=lambda x: x["revenue"], reverse=True)

        # Offer health
        off_health: list[dict] = []
        if not ofr.empty:
            for _, r in ofr.iterrows():
                mp = float(r["margin_pct"]); rev = float(r["revenue"])
                off_health.append(dict(offerName=r["offerName"], revenue=round(rev, 2),
                    profit=round(float(r["profit"]), 2), margin_pct=round(mp, 2),
                    installs=int(r["installs"]), status=_status(mp)))
        off_health.sort(key=lambda x: x["revenue"], reverse=True)

        # Funnel issues
        funnel_issues: list[dict] = []
        if not dod.empty:
            for _, r in dod.iterrows():
                p_conv = float(r["conv_p"]); c_conv = float(r["conv_y"])
                p_vld  = float(r["valid_p"]); c_vld  = float(r["valid_y"])
                if p_conv < 10 or c_conv < 10: continue
                prev_cr = p_vld / p_conv * 100; curr_cr = c_vld / c_conv * 100
                if prev_cr > 0 and curr_cr < prev_cr * 0.7:
                    drop = round((prev_cr - curr_cr) / prev_cr * 100, 1)
                    funnel_issues.append(dict(offerName=r["offerName"],
                        prev_conv_rate=round(prev_cr, 2), curr_conv_rate=round(curr_cr, 2),
                        drop_pct=drop, curr_conversions=int(c_conv)))
        funnel_issues.sort(key=lambda x: x["drop_pct"], reverse=True)

        # Anomaly groups
        margin_collapse: list[dict] = []
        revenue_drop_anom: list[dict] = []
        install_drop_anom: list[dict] = []
        revenue_spike_anom: list[dict] = []
        if not ofr.empty:
            for _, r in ofr.iterrows():
                mp = float(r["margin_pct"]); rev = float(r["revenue"])
                if mp < 5 and rev >= MIN_REV:
                    margin_collapse.append(dict(offerName=r["offerName"], margin_pct=round(mp, 2), revenue=round(rev, 2)))
        margin_collapse.sort(key=lambda x: x["margin_pct"])
        if not dod.empty:
            for _, r in dod.iterrows():
                p_rev = float(r["revenue_p"]); y_rev = float(r["revenue_y"])
                p_inst = float(r["installs_p"]); y_inst = float(r["installs_y"])
                if p_rev >= MIN_REV:
                    if y_rev < p_rev * 0.6:
                        revenue_drop_anom.append(dict(offerName=r["offerName"],
                            drop_pct=round((p_rev - y_rev) / p_rev * 100, 1), base_revenue=round(p_rev, 2)))
                    elif y_rev > p_rev * 1.5:
                        revenue_spike_anom.append(dict(offerName=r["offerName"],
                            spike_pct=round((y_rev - p_rev) / p_rev * 100, 1), revenue=round(y_rev, 2)))
                if p_inst >= MIN_INST and y_inst < p_inst * 0.6:
                    install_drop_anom.append(dict(offerName=r["offerName"],
                        drop_pct=round((p_inst - y_inst) / p_inst * 100, 1), base_installs=int(p_inst)))
        revenue_drop_anom.sort(key=lambda x: x["base_revenue"], reverse=True)
        install_drop_anom.sort(key=lambda x: x["base_installs"], reverse=True)
        revenue_spike_anom.sort(key=lambda x: x["revenue"], reverse=True)

        # Priorities
        priorities: list[dict] = []
        for item in [x for x in risk_items if x["severity"] == "critical"][:5]:
            priorities.append(dict(severity="critical", type="margin_risk",
                entity_type="offer", entity=item["offerName"], detail=item["reasons"][0],
                revenue=item["revenue"], margin_pct=item["margin_pct"]))
        for item in revenue_drop_anom[:3]:
            priorities.append(dict(severity="warning", type="revenue_drop",
                entity_type="offer", entity=item["offerName"],
                detail=f"Revenue dropped {item['drop_pct']:.0f}% yesterday",
                revenue=item["base_revenue"], margin_pct=None))
        for item in [p for p in pub_health if p["status"] == "at_risk"][:2]:
            priorities.append(dict(severity="critical", type="publisher_risk",
                entity_type="publisher", entity=item["partner"],
                detail=f"Negative margin ({item['margin_pct']:.1f}%)",
                revenue=item["revenue"], margin_pct=item["margin_pct"]))
        for item in scale_items[:3]:
            priorities.append(dict(severity="success", type="scale_opportunity",
                entity_type="offer", entity=item["offerName"],
                detail=f"{item['margin_pct']:.1f}% margin — ready to scale",
                revenue=item["revenue"], margin_pct=item["margin_pct"]))

        seen: set[str] = set(); deduped: list[dict] = []
        for p in priorities:
            if p["entity"] not in seen:
                seen.add(p["entity"]); deduped.append(p)
        _sev = {"critical": 0, "warning": 1, "success": 2}
        deduped.sort(key=lambda x: (_sev.get(x["severity"], 9), -(x["revenue"] or 0)))

        def _grp(lst, n=3):
            return dict(count=len(lst), examples=lst[:n])

        return dict(
            priorities=deduped[:10],
            revenue_at_risk=risk_items,
            scale_opportunities=scale_items[:10],
            publisher_health=pub_health[:25],
            offer_health=off_health[:25],
            funnel_issues=funnel_issues[:15],
            anomaly_groups=dict(
                margin_collapse=_grp(margin_collapse),
                revenue_drop=_grp(revenue_drop_anom),
                install_drop=_grp(install_drop_anom),
                revenue_spike=_grp(revenue_spike_anom),
            ),
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Operations
    # ══════════════════════════════════════════════════════════════════════════

    def operations_recommendations(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return {"offers": []}

        stats = (
            filtered.groupby(["partner", "offerName"], as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 conversions=("conversions","sum"),
                 valid_conversions=("valid_conversions","sum"))
        )
        inst_stats = (
            filtered.groupby(["partner", "offerName"], as_index=False)
            .agg(installs=("unique_installs", "sum"))
        )
        stats = stats.merge(inst_stats, on=["partner", "offerName"], how="left")
        stats["installs"] = stats["installs"].fillna(0).astype(int)
        stats["profit"]     = stats["revenue"] - stats["payout"]
        stats["margin_pct"] = (
            stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100
        ).round(2).fillna(0)

        def _action(mp):
            if mp < 0:   return "Pause",    "critical"
            if mp < 15:  return "Optimize", "warning"
            if mp <= 30: return "Monitor",  "info"
            return "Scale", "success"

        rows = []
        for _, r in stats.iterrows():
            action, severity = _action(float(r["margin_pct"]))
            rows.append(dict(
                partner=r["partner"], offerName=r["offerName"],
                revenue=round(float(r["revenue"]),2), cost=round(float(r["payout"]),2),
                profit=round(float(r["profit"]),2),   margin_pct=round(float(r["margin_pct"]),2),
                conversions=int(r["conversions"]),     valid_conversions=int(r["valid_conversions"]),
                installs=int(r["installs"]), action=action, severity=severity))
        rows.sort(key=lambda x: x["revenue"], reverse=True)
        return {"offers": rows}

    # ══════════════════════════════════════════════════════════════════════════
    # Publishers
    # ══════════════════════════════════════════════════════════════════════════

    def publishers_kpis(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
        configured_publishers: list[dict],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)

        rev = cost = 0.0
        if not filtered.empty:
            rev  = float(filtered["revenue"].sum())
            cost = float(filtered["payout"].sum())
        profit     = round(rev - cost, 2)
        profit_pct = round(profit / rev * 100, 2) if rev else 0.0

        active_in_data = set(filtered["partner"].dropna().unique()) if not filtered.empty else set()
        active_list: list[str] = []
        paused_list: list[str] = []
        for rec in configured_publishers:
            pid = str(rec.get("publisher_id", "")).strip()
            if not pid: continue
            (active_list if pid in active_in_data else paused_list).append(pid)

        return {
            "total_configured": len(configured_publishers),
            "total_revenue":    round(rev, 2),
            "total_profit":     profit,
            "profit_pct":       profit_pct,
            "active_count":     len(active_list),
            "paused_count":     len(paused_list),
            "configured_list":  configured_publishers,
            "active_list":      active_list,
            "paused_list":      paused_list,
        }

    def publishers_detail(
        self,
        partner:  str,
        from_date: dt.date, to_date: dt.date,
        offers: list[str], goals: list[str],
    ) -> dict:
        df = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, [partner], offers, goals)

        if filtered.empty:
            return {"partner": partner,
                    "stats": {"revenue":0,"cost":0,"profit":0,"margin_pct":0,
                               "active_offers":0,"conversions":0,"installs":0},
                    "offers": []}

        rev  = float(filtered["revenue"].sum())
        cost = float(filtered["payout"].sum())
        pft  = rev - cost
        stats = {
            "revenue":       round(rev, 2), "cost": round(cost, 2),
            "profit":        round(pft, 2),
            "margin_pct":    round(pft / rev * 100, 2) if rev else 0.0,
            "active_offers": int(filtered["offerName"].nunique()),
            "conversions":   int(filtered["conversions"].sum()),
            "installs":      int(filtered["unique_installs"].sum()),
            "revenue_source": str(filtered["revenue_source"].iloc[0]),
        }
        odf = (
            filtered.groupby("offerName", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 conversions=("conversions","sum"),
                 valid_conversions=("valid_conversions","sum"),
                 revenue_source=("revenue_source","first"))
            .sort_values("revenue", ascending=False).reset_index(drop=True)
        )
        inst_odf = filtered.groupby("offerName", as_index=False).agg(installs=("unique_installs","sum"))
        odf = odf.merge(inst_odf, on="offerName", how="left")
        odf["installs"]   = odf["installs"].fillna(0).astype(int)
        odf["profit"]     = (odf["revenue"] - odf["payout"]).round(2)
        odf["margin_pct"] = (odf["profit"] / odf["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            odf[col] = odf[col].round(2)
        return {"partner": partner, "stats": stats, "offers": odf.to_dict(orient="records")}

    def publishers_profile(
        self,
        partner:   str,
        from_date: dt.date, to_date: dt.date,
        offers: list[str], goals: list[str],
    ) -> dict:
        df     = self.get_enriched_summary()
        all_df = self.slice_summary(df, from_date, to_date, [], offers, goals)
        pub_df = self.slice_summary(df, from_date, to_date, [partner], offers, goals)

        if pub_df.empty:
            return {"stats": {}, "offers": [], "trend": [], "ranking": {}, "activity": {}}

        rev  = float(pub_df["revenue"].sum())
        cost = float(pub_df["payout"].sum())
        pft  = rev - cost
        total_rev = float(all_df["revenue"].sum()) if not all_df.empty else 0

        stats = {
            "revenue":       round(rev, 2), "cost": round(cost, 2),
            "profit":        round(pft, 2),
            "margin_pct":    round(pft / rev * 100, 2) if rev else 0.0,
            "installs":      int(pub_df["unique_installs"].sum()),
            "active_offers": int(pub_df["offerName"].nunique()),
            "revenue_share": round(rev / total_rev * 100, 1) if total_rev > 0 else 0.0,
            "revenue_source": str(pub_df["revenue_source"].iloc[0]),
        }

        odf = (
            pub_df.groupby("offerName", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 revenue_source=("revenue_source","first"))
        )
        inst_odf = pub_df.groupby("offerName", as_index=False).agg(installs=("unique_installs","sum"))
        odf = odf.merge(inst_odf, on="offerName", how="left")
        odf["installs"]   = odf["installs"].fillna(0).astype(int)
        odf["profit"]     = (odf["revenue"] - odf["payout"]).round(2)
        odf["margin_pct"] = (odf["profit"] / odf["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            odf[col] = odf[col].round(2)
        odf = odf.rename(columns={"payout": "cost"}).sort_values("revenue", ascending=False).reset_index(drop=True)

        last_act      = pub_df.groupby("offerName")["date"].max()
        last_act_dict = {n: d for n, d in zip(last_act.index, pd.to_datetime(last_act).dt.date)}
        active_threshold = to_date - dt.timedelta(days=7)
        recent_cutoff    = to_date - dt.timedelta(days=7)
        prev_cutoff      = to_date - dt.timedelta(days=14)
        pub_date_col     = pd.to_datetime(pub_df["date"]).dt.date
        recent_rev = pub_df[pub_date_col >= recent_cutoff].groupby("offerName")["revenue"].sum().to_dict()
        prev_rev   = pub_df[(pub_date_col >= prev_cutoff) & (pub_date_col < recent_cutoff)].groupby("offerName")["revenue"].sum().to_dict()

        def _offer_trend(name):
            r = float(recent_rev.get(name, 0)); p = float(prev_rev.get(name, 0))
            if p == 0: return "up" if r > 0 else "stable"
            ratio = r / p
            return "up" if ratio > 1.10 else ("down" if ratio < 0.90 else "stable")

        odf["last_activity"] = odf["offerName"].map(lambda n: str(last_act_dict[n]) if n in last_act_dict else "")
        odf["is_active"]     = odf["offerName"].map(lambda n: last_act_dict.get(n, dt.date.min) >= active_threshold)
        odf["trend"]         = odf["offerName"].map(_offer_trend)

        daily = (
            pub_df.groupby("date", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"), installs=("unique_installs","sum"))
        )
        daily["installs"]   = daily["installs"].astype(int)
        daily["profit"]     = (daily["revenue"] - daily["payout"]).round(2)
        daily["margin_pct"] = (daily["profit"] / daily["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            daily[col] = daily[col].round(2)
        daily = daily.rename(columns={"payout": "cost"})
        daily["date"] = daily["date"].astype(str)
        daily = daily.sort_values("date").reset_index(drop=True)

        ranking = {}
        if not all_df.empty:
            all_pub = (
                all_df.groupby("partner", as_index=False)
                .agg(revenue=("revenue","sum"), payout=("payout","sum"))
            )
            all_pub["profit"]     = all_pub["revenue"] - all_pub["payout"]
            all_pub["margin_pct"] = (all_pub["profit"] / all_pub["revenue"].replace(0, float("nan")) * 100).fillna(0)
            def _rank(col):
                s = all_pub.sort_values(col, ascending=False).reset_index(drop=True)
                m = s[s["partner"] == partner]
                return int(m.index[0]) + 1 if not m.empty else None
            ranking = {"revenue_rank": _rank("revenue"), "profit_rank": _rank("profit"),
                       "margin_rank": _rank("margin_pct"), "total": len(all_pub)}

        return {
            "stats": stats, "offers": odf.to_dict(orient="records"),
            "trend": daily.to_dict(orient="records"), "ranking": ranking,
            "activity": {"first_seen": str(pub_df["date"].min()), "last_activity": str(pub_df["date"].max())},
        }

    def pub_offer_detail(
        self,
        partner: str, offer: str,
        from_date: dt.date, to_date: dt.date,
        goals: list[str],
    ) -> dict:
        df     = self.get_enriched_summary()
        pod_df = self.slice_summary(df, from_date, to_date, [partner], [offer], goals)

        if pod_df.empty:
            return {"stats": {}, "trend": [], "activity": {}}

        rev  = float(pod_df["revenue"].sum())
        cost = float(pod_df["payout"].sum())
        pft  = rev - cost
        stats = {
            "revenue": round(rev, 2), "cost": round(cost, 2),
            "profit":  round(pft, 2),
            "margin_pct":  round(pft / rev * 100, 2) if rev else 0.0,
            "installs":    int(pod_df["unique_installs"].sum()),
            "conversions": int(pod_df["conversions"].sum()),
            "revenue_source": str(pod_df["revenue_source"].iloc[0]),
        }
        daily = (
            pod_df.groupby("date", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"), installs=("unique_installs","sum"))
        )
        daily["installs"]   = daily["installs"].astype(int)
        daily["profit"]     = (daily["revenue"] - daily["payout"]).round(2)
        daily["margin_pct"] = (daily["profit"] / daily["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            daily[col] = daily[col].round(2)
        daily["date"] = daily["date"].astype(str)
        daily = daily.sort_values("date").reset_index(drop=True)

        funnel_data = self._funnel_svc.build_funnel([offer], from_date, to_date, [partner])
        return {
            "stats": stats, "trend": daily.to_dict(orient="records"),
            "activity": {"first_seen": str(pod_df["date"].min()),
                         "last_activity": str(pod_df["date"].max()),
                         "active_days": int(pod_df["date"].nunique())},
            "funnel": funnel_data["steps"],
            "funnel_summary": {k: funnel_data[k] for k in ("total_users","final_count","overall_rate","total_dropoff","total_dropoff_pct")},
            "has_expected": funnel_data["has_expected"], "funnel_mode": funnel_data["mode"],
        }

    def publishers_summary(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return {"publishers": []}
        stats = (
            filtered.groupby("partner", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 conversions=("conversions","sum"),
                 valid_conversions=("valid_conversions","sum"),
                 active_offers=("offerName","nunique"))
        )
        inst_df = filtered.groupby("partner", as_index=False).agg(installs=("unique_installs","sum"))
        stats = stats.merge(inst_df, on="partner", how="left")
        stats["installs"]   = stats["installs"].fillna(0).astype(int)
        stats["profit"]     = stats["revenue"] - stats["payout"]
        stats["margin_pct"] = (stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        stats["conv_rate"]  = (stats["valid_conversions"] / stats["conversions"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            stats[col] = stats[col].round(2)
        return {"publishers": stats.sort_values("revenue", ascending=False).reset_index(drop=True).to_dict(orient="records")}

    def publishers_comparison(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        if not offers:
            raise ValueError("no_offer")
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return {"publishers": [], "offers": offers}
        stats = (
            filtered.groupby(["partner","offerName"], as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 conversions=("conversions","sum"), valid_conversions=("valid_conversions","sum"))
        )
        stats["profit"]     = stats["revenue"] - stats["payout"]
        stats["margin_pct"] = (stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        stats["conv_rate"]  = (stats["valid_conversions"] / stats["conversions"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            stats[col] = stats[col].round(2)
        return {"publishers": stats.sort_values("revenue", ascending=False).to_dict(orient="records"), "offers": offers}

    # ══════════════════════════════════════════════════════════════════════════
    # Offers
    # ══════════════════════════════════════════════════════════════════════════

    def offers_profile(
        self,
        offer: str,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], goals: list[str],
    ) -> dict:
        df      = self.get_enriched_summary()
        all_df  = self.slice_summary(df, from_date, to_date, partners, [], goals)
        off_df  = self.slice_summary(df, from_date, to_date, partners, [offer], goals)

        if off_df.empty:
            return {"stats": {}, "publishers": [], "trend": [],
                    "ranking": {}, "activity": {}, "funnel": [], "funnel_summary": {}}

        rev  = float(off_df["revenue"].sum()); cost = float(off_df["payout"].sum()); pft = rev - cost
        total_rev = float(all_df["revenue"].sum()) if not all_df.empty else 0
        stats = {
            "revenue": round(rev, 2), "cost": round(cost, 2), "profit": round(pft, 2),
            "margin_pct": round(pft / rev * 100, 2) if rev else 0.0,
            "installs": int(off_df["unique_installs"].sum()),
            "active_publishers": int(off_df["partner"].nunique()),
            "revenue_share": round(rev / total_rev * 100, 1) if total_rev > 0 else 0.0,
            "revenue_source": str(off_df["revenue_source"].iloc[0]),
        }

        pdf = off_df.groupby("partner", as_index=False).agg(revenue=("revenue","sum"), payout=("payout","sum"))
        inst_pdf = off_df.groupby("partner", as_index=False).agg(installs=("unique_installs","sum"))
        pdf = pdf.merge(inst_pdf, on="partner", how="left")
        pdf["installs"]   = pdf["installs"].fillna(0).astype(int)
        pdf["profit"]     = (pdf["revenue"] - pdf["payout"]).round(2)
        pdf["margin_pct"] = (pdf["profit"] / pdf["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            pdf[col] = pdf[col].round(2)
        pdf = pdf.rename(columns={"payout": "cost"}).sort_values("revenue", ascending=False).reset_index(drop=True)

        last_act      = off_df.groupby("partner")["date"].max()
        last_act_dict = {n: d for n, d in zip(last_act.index, pd.to_datetime(last_act).dt.date)}
        active_threshold = to_date - dt.timedelta(days=7)
        recent_cutoff    = to_date - dt.timedelta(days=7)
        prev_cutoff      = to_date - dt.timedelta(days=14)
        off_date_col     = pd.to_datetime(off_df["date"]).dt.date
        recent_rev = off_df[off_date_col >= recent_cutoff].groupby("partner")["revenue"].sum().to_dict()
        prev_rev   = off_df[(off_date_col >= prev_cutoff) & (off_date_col < recent_cutoff)].groupby("partner")["revenue"].sum().to_dict()

        def _pub_trend(pid):
            r = float(recent_rev.get(pid, 0)); p = float(prev_rev.get(pid, 0))
            if p == 0: return "up" if r > 0 else "stable"
            ratio = r / p
            return "up" if ratio > 1.10 else ("down" if ratio < 0.90 else "stable")

        pdf["last_activity"] = pdf["partner"].map(lambda n: str(last_act_dict[n]) if n in last_act_dict else "")
        pdf["is_active"]     = pdf["partner"].map(lambda n: last_act_dict.get(n, dt.date.min) >= active_threshold)
        pdf["trend"]         = pdf["partner"].map(_pub_trend)

        daily = (
            off_df.groupby("date", as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"), installs=("unique_installs","sum"))
        )
        daily["installs"]   = daily["installs"].astype(int)
        daily["profit"]     = (daily["revenue"] - daily["payout"]).round(2)
        daily["margin_pct"] = (daily["profit"] / daily["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            daily[col] = daily[col].round(2)
        daily = daily.rename(columns={"payout": "cost"})
        daily["date"] = daily["date"].astype(str)
        daily = daily.sort_values("date").reset_index(drop=True)

        ranking = {}
        if not all_df.empty:
            all_offers = (all_df.groupby("offerName", as_index=False).agg(revenue=("revenue","sum"), payout=("payout","sum")))
            all_offers["profit"]     = all_offers["revenue"] - all_offers["payout"]
            all_offers["margin_pct"] = (all_offers["profit"] / all_offers["revenue"].replace(0, float("nan")) * 100).fillna(0)
            def _rank(col):
                s = all_offers.sort_values(col, ascending=False).reset_index(drop=True)
                m = s[s["offerName"] == offer]
                return int(m.index[0]) + 1 if not m.empty else None
            ranking = {"revenue_rank": _rank("revenue"), "profit_rank": _rank("profit"),
                       "margin_rank": _rank("margin_pct"), "total": len(all_offers)}

        funnel_data = self._funnel_svc.build_funnel([offer], from_date, to_date, partners or [])
        return {
            "stats": stats, "publishers": pdf.to_dict(orient="records"),
            "trend": daily.to_dict(orient="records"), "ranking": ranking,
            "activity": {"first_seen": str(off_df["date"].min()), "last_activity": str(off_df["date"].max())},
            "funnel": funnel_data["steps"],
            "funnel_summary": {k: funnel_data[k] for k in ("total_users","final_count","overall_rate","total_dropoff","total_dropoff_pct")},
            "has_expected": funnel_data["has_expected"], "funnel_mode": funnel_data["mode"],
        }

    def offers_summary(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)

        all_base = df
        if partners:  all_base = all_base[all_base["partner"].isin(partners)]
        if offers:    all_base = all_base[all_base["offerName"].isin(offers)]
        if goals:     all_base = all_base[all_base["goal"].isin(goals)]
        all_offer_names: set[str] = set(all_base["offerName"].dropna().unique())

        def _action(mp: float) -> str:
            if mp < 0:   return "Pause"
            if mp < 15:  return "Optimize"
            if mp <= 30: return "Monitor"
            return "Scale"

        if not filtered.empty:
            stats = (
                filtered.groupby("offerName", as_index=False)
                .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                     conversions=("conversions","sum"),
                     valid_conversions=("valid_conversions","sum"),
                     goals_count=("goal","nunique"),
                     active_publishers=("partner","nunique"),
                     first_seen=("date","min"), last_seen=("date","max"),
                     revenue_source=("revenue_source","first"))
                .sort_values("revenue", ascending=False)
            )
            inst_df = filtered.groupby("offerName", as_index=False).agg(installs=("unique_installs","sum"))
            stats = stats.merge(inst_df, on="offerName", how="left")
            stats["installs"]   = stats["installs"].fillna(0).astype(int)
            stats["profit"]     = stats["revenue"] - stats["payout"]
            stats["margin_pct"] = (stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
            stats["valid_pct"]  = (stats["valid_conversions"] / stats["conversions"].replace(0, float("nan")) * 100).round(2).fillna(0)
            for col in ("revenue","payout","profit"):
                stats[col] = stats[col].round(2)
            stats["first_seen"] = stats["first_seen"].astype(str)
            stats["last_seen"]  = stats["last_seen"].astype(str)
            stats["action"]     = stats["margin_pct"].apply(_action)
            stats["status"]     = "active"
            active_names: set[str] = set(stats["offerName"].tolist())
        else:
            stats = pd.DataFrame(); active_names = set()

        paused_names = all_offer_names - active_names
        if paused_names:
            paused_data = all_base[all_base["offerName"].isin(paused_names)]
            if not paused_data.empty:
                pstats = (
                    paused_data.groupby("offerName", as_index=False)
                    .agg(active_publishers=("partner","nunique"), goals_count=("goal","nunique"),
                         first_seen=("date","min"), last_seen=("date","max"))
                )
                for col in ("revenue","payout","conversions","valid_conversions",
                            "installs","profit","valid_pct","margin_pct"):
                    pstats[col] = 0
                pstats["first_seen"] = pstats["first_seen"].astype(str)
                pstats["last_seen"]  = pstats["last_seen"].astype(str)
                pstats["action"]     = "Pause"; pstats["status"] = "paused"
                stats = pd.concat([stats, pstats], ignore_index=True) if not stats.empty else pstats

        if stats.empty:
            return {"offers": [], "kpis": {}}

        stats["_s"] = stats["status"].apply(lambda x: 0 if x == "active" else 1)
        stats = stats.sort_values(["_s","revenue"], ascending=[True,False]).drop(columns=["_s"]).reset_index(drop=True)

        active_df  = stats[stats["status"] == "active"]
        total_inst = int(stats["installs"].sum())
        days_in_rng = max(1, (to_date - from_date).days + 1) if (from_date and to_date) else 1
        kpis = dict(
            total_offers=int(len(stats)), active_offers=int(len(active_df)),
            paused_offers=int((stats["status"] == "paused").sum()),
            total_revenue=round(float(active_df["revenue"].sum()), 2),
            total_cost=round(float(active_df["payout"].sum()), 2),
            total_profit=round(float(active_df["profit"].sum()), 2),
            total_conversions=int(active_df["conversions"].sum()),
            total_installs=total_inst,
            avg_installs_per_day=round(total_inst / days_in_rng, 1),
            action_counts=dict(
                scale=int((active_df["action"] == "Scale").sum()),
                monitor=int((active_df["action"] == "Monitor").sum()),
                optimize=int((active_df["action"] == "Optimize").sum()),
                pause=int((active_df["action"] == "Pause").sum()),
            ),
        )
        return {"offers": stats.to_dict(orient="records"), "kpis": kpis}

    def offers_publishers(
        self,
        from_date: dt.date, to_date: dt.date,
        partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        if not offers:
            raise ValueError("no_offer")
        df       = self.get_enriched_summary()
        filtered = self.slice_summary(df, from_date, to_date, partners, offers, goals)
        if filtered.empty:
            return {"publishers": [], "offers": offers}
        stats = (
            filtered.groupby(["offerName","partner"], as_index=False)
            .agg(revenue=("revenue","sum"), payout=("payout","sum"),
                 conversions=("conversions","sum"), valid_conversions=("valid_conversions","sum"))
        )
        stats["profit"]     = stats["revenue"] - stats["payout"]
        stats["margin_pct"] = (stats["profit"] / stats["revenue"].replace(0, float("nan")) * 100).round(2).fillna(0)
        for col in ("revenue","payout","profit"):
            stats[col] = stats[col].round(2)
        return {"publishers": stats.sort_values("revenue", ascending=False).to_dict(orient="records"), "offers": offers}

    def offers_map(self, available_dates: list, raw_path_fn=None) -> dict:
        """
        Build {offerName: offer_id} map by scanning raw parquet files.

        Uses the active StorageProvider (works with both local and S3).
        raw_path_fn is kept for backward-compat but is no longer used.
        """
        from backend.storage import get_provider as _get_storage
        storage    = _get_storage()
        conf_names = self.get_configured_offer_names()
        result: dict[str, str] = {}

        def _norm_oid(v: str) -> str:
            s = str(v)
            return str(int(float(s))) if s.replace(".0", "").isdigit() else s.strip()

        for date in available_dates:
            try:
                if not storage.raw_day_exists(date):
                    continue
                pairs = storage.load_raw_day(date, columns=["offerName", "offer"])
                if pairs.empty:
                    continue
                pairs = pairs.dropna().drop_duplicates()
                for name, offer in zip(
                    pairs["offerName"].astype(str).str.strip(),
                    pairs["offer"].astype(str),
                ):
                    if name and name not in result and (not conf_names or name in conf_names):
                        result[name] = _norm_oid(offer)
            except Exception:
                pass
        return result

    # ══════════════════════════════════════════════════════════════════════════
    # Analytics
    # ══════════════════════════════════════════════════════════════════════════

    def analytics_weekly(
        self, partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df    = self.get_enriched_summary()
        today = ist_today()
        weeks = []
        for i in range(7, -1, -1):
            w_end   = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=i) - dt.timedelta(days=1)
            w_start = w_end - dt.timedelta(days=6)
            if w_start > today: continue
            w_end = min(w_end, today)
            w_df  = self.slice_summary(df, w_start, w_end, partners, offers, goals)
            rev   = round(float(w_df["revenue"].sum()), 2) if not w_df.empty else 0
            cost  = round(float(w_df["payout"].sum()), 2) if not w_df.empty else 0
            conv  = int(w_df["conversions"].sum()) if not w_df.empty else 0
            profit = round(rev - cost, 2)
            weeks.append(dict(week=f"W{w_start.isocalendar()[1]}", period=f"{w_start} → {w_end}",
                revenue=rev, cost=cost, profit=profit,
                margin_pct=round(profit/rev*100, 2) if rev else 0, conversions=conv))
        for i in range(1, len(weeks)):
            weeks[i]["wow_revenue_pct"] = self.pct_change(weeks[i]["revenue"], weeks[i-1]["revenue"])
            weeks[i]["wow_profit_pct"]  = self.pct_change(weeks[i]["profit"],  weeks[i-1]["profit"])
        if weeks:
            weeks[0]["wow_revenue_pct"] = None; weeks[0]["wow_profit_pct"] = None
        return {"weeks": weeks}

    def analytics_monthly(
        self, partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df    = self.get_enriched_summary()
        today = ist_today()
        months = []
        for i in range(5, -1, -1):
            m_start = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
            for _ in range(i):
                m_start = (m_start - dt.timedelta(days=1)).replace(day=1)
            m_end = today if i == 0 else (m_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            m_df  = self.slice_summary(df, m_start, m_end, partners, offers, goals)
            rev   = round(float(m_df["revenue"].sum()), 2) if not m_df.empty else 0
            cost  = round(float(m_df["payout"].sum()), 2) if not m_df.empty else 0
            conv  = int(m_df["conversions"].sum()) if not m_df.empty else 0
            profit = round(rev - cost, 2)
            months.append(dict(month=m_start.strftime("%b %Y"), period=f"{m_start} → {m_end}",
                revenue=rev, cost=cost, profit=profit,
                margin_pct=round(profit/rev*100, 2) if rev else 0, conversions=conv))
        for i in range(1, len(months)):
            months[i]["mom_revenue_pct"] = self.pct_change(months[i]["revenue"], months[i-1]["revenue"])
            months[i]["mom_profit_pct"]  = self.pct_change(months[i]["profit"],  months[i-1]["profit"])
        if months:
            months[0]["mom_revenue_pct"] = None; months[0]["mom_profit_pct"] = None
        return {"months": months}

    def analytics_drivers(
        self, partners: list[str], offers: list[str], goals: list[str],
    ) -> dict:
        df    = self.get_enriched_summary()
        today = ist_today()
        curr_start = today - dt.timedelta(days=6);  curr_end = today
        prev_start = today - dt.timedelta(days=13); prev_end = today - dt.timedelta(days=7)
        curr_df = self.slice_summary(df, curr_start, curr_end, partners, offers, goals)
        prev_df = self.slice_summary(df, prev_start, prev_end, partners, offers, goals)

        def _agg(d, col):
            if d.empty: return pd.DataFrame(columns=[col, "revenue", "payout"])
            return d.groupby(col, as_index=False).agg(revenue=("revenue","sum"), payout=("payout","sum"))

        def _margin(rev, payout):
            p = rev - payout
            return round(p / rev * 100, 1) if rev > 0 else 0.0

        def _compare(c_df, p_df, group_col, label):
            c = _agg(c_df, group_col); p = _agg(p_df, group_col)
            m = pd.merge(c, p, on=group_col, suffixes=("_c","_p"), how="outer").fillna(0)
            m["curr_rev"]    = m["revenue_c"].round(2); m["prev_rev"]    = m["revenue_p"].round(2)
            m["curr_profit"] = (m["revenue_c"] - m["payout_c"]).round(2)
            m["prev_profit"] = (m["revenue_p"] - m["payout_p"]).round(2)
            m["curr_margin"] = m.apply(lambda r: _margin(r["revenue_c"], r["payout_c"]), axis=1)
            m["prev_margin"] = m.apply(lambda r: _margin(r["revenue_p"], r["payout_p"]), axis=1)
            m["delta_rev"]   = (m["curr_rev"] - m["prev_rev"]).round(2)
            m["delta_profit"]= (m["curr_profit"] - m["prev_profit"]).round(2)
            m["delta_margin"]= (m["curr_margin"] - m["prev_margin"]).round(1)
            m = m.rename(columns={group_col: label})
            cols = [label, "curr_rev","prev_rev","delta_rev","curr_profit","prev_profit","delta_profit","curr_margin","prev_margin","delta_margin"]
            gainers   = m[m["delta_rev"] > 0].sort_values("delta_rev", ascending=False).head(5)[cols].to_dict("records")
            decliners = m[m["delta_rev"] < 0].sort_values("delta_rev", ascending=True).head(5)[cols].to_dict("records")
            is_new    = m["prev_rev"] == 0
            new_names = m[is_new & (m["curr_rev"] > 0)][label].tolist()
            new_rev   = round(float(m[is_new]["curr_rev"].sum()), 2)
            exist_rev = round(float(m[~is_new]["curr_rev"].sum()), 2)
            total_rev = round(new_rev + exist_rev, 2)
            return gainers, decliners, new_names, {
                "new_rev": new_rev, "exist_rev": exist_rev, "total_rev": total_rev,
                "new_pct": round(new_rev/total_rev*100, 1) if total_rev else 0,
                "exist_pct": round(exist_rev/total_rev*100, 1) if total_rev else 0,
            }

        pg, pd_, pn, p_nve = _compare(curr_df, prev_df, "partner",   "partner")
        og, od, on_, o_nve = _compare(curr_df, prev_df, "offerName", "offerName")
        return {
            "period": {
                "current":  f"{curr_start.strftime('%b %d')} – {curr_end.strftime('%b %d')}",
                "previous": f"{prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d')}",
            },
            "publishers": {"gainers": pg, "decliners": pd_, "new": pn, "new_vs_existing": p_nve},
            "offers":     {"gainers": og, "decliners": od,  "new": on_, "new_vs_existing": o_nve},
        }

    def funnel_data(
        self,
        offers: list[str],
        from_date: dt.date, to_date: dt.date,
        partners: list[str],
    ) -> dict:
        conf_names = self.get_configured_offer_names()
        if conf_names and offers:
            offers = [o for o in offers if o in conf_names]
        result = self._funnel_svc.build_funnel(offers, from_date, to_date, partners or [])
        result["offers"] = offers
        return result
