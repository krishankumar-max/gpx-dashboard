"""
GameConfigService — business logic for game configuration CRUD and discovery.

Owns:
  - Create / Update / Delete with validation and cache invalidation
  - Scan raw parquet files to discover configured vs unconfigured offers
  - Dashboard status counts

Repositories persist; this service decides what is valid and what the data means.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from backend.repositories.base import GameConfigRepository
from backend.repositories.cache import CacheProvider
from backend.utils import ist_now

if TYPE_CHECKING:
    from backend.storage.base import StorageProvider

_IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Cache keys that must be evicted after any game-config write
_CACHE_KEYS = ("gcfg", "oid_map", "edf")


def _safe_kpi(v, fallback: dict | None = None) -> dict:
    default = fallback if isinstance(fallback, dict) else {"retention": [], "roas": []}
    if not isinstance(v, dict):
        return default
    return {
        "retention": v.get("retention", []) if isinstance(v.get("retention"), list) else [],
        "roas":      v.get("roas", [])      if isinstance(v.get("roas"),      list) else [],
    }


class GameConfigService:
    """Business logic for game configurations."""

    def __init__(
        self,
        repo:    GameConfigRepository,
        cache:   CacheProvider,
        storage: "StorageProvider | None" = None,
    ) -> None:
        self._repo    = repo
        self._cache   = cache
        self._storage = storage

    # ── Read ──────────────────────────────────────────────────────────────────

    def list(self) -> list[dict]:
        """Return all game config records as plain dicts."""
        return self._repo.get_all_raw()

    # ── Write ─────────────────────────────────────────────────────────────────

    def create(self, body: dict) -> dict:
        """
        Validate and persist a new game config record.

        Raises
        ------
        ValueError  — offer_id missing
        Conflict    — a config for this offer_id already exists
        """
        import uuid

        if not body.get("offer_id"):
            raise ValueError("offer_id is required")

        records = self._repo.get_all_raw()
        if any(r.get("offer_id") == str(body["offer_id"]) for r in records):
            raise _Conflict("Configuration already exists for this offer")

        em = body.get("expected_margin")
        record = {
            "id":              str(uuid.uuid4()),
            "offer_id":        str(body.get("offer_id",   "")).strip(),
            "offer_name":      str(body.get("offer_name", "")).strip(),
            "game_type":       str(body.get("game_type",  "CPI")).strip(),
            "payable_goals":   body.get("payable_goals",  []) if isinstance(body.get("payable_goals"), list) else [],
            "publisher_kpi":   _safe_kpi(body.get("publisher_kpi")),
            "client_kpi":      _safe_kpi(body.get("client_kpi")),
            "expected_funnel": body.get("expected_funnel", []) if isinstance(body.get("expected_funnel"), list) else [],
            "expected_margin": float(em) if em is not None and em != "" else None,
            "configured_at":   ist_now().isoformat(),
        }
        self._repo.create(record)
        self._invalidate()
        return record

    def update(self, cid: str, body: dict) -> dict | None:
        """Update a game config by id.  Returns updated dict or None if not found."""
        records = self._repo.get_all_raw()
        for rec in records:
            if rec.get("id") == cid:
                em = body.get("expected_margin")
                rec.update({
                    "game_type":       str(body.get("game_type", rec.get("game_type", "CPI"))).strip(),
                    "payable_goals":   body.get("payable_goals", rec.get("payable_goals", []))
                                       if isinstance(body.get("payable_goals"), list)
                                       else rec.get("payable_goals", []),
                    "publisher_kpi":   _safe_kpi(body.get("publisher_kpi"),  rec.get("publisher_kpi")),
                    "client_kpi":      _safe_kpi(body.get("client_kpi"),     rec.get("client_kpi")),
                    "expected_funnel": body.get("expected_funnel", rec.get("expected_funnel", []))
                                       if isinstance(body.get("expected_funnel"), list)
                                       else rec.get("expected_funnel", []),
                    "expected_margin": float(em) if em is not None and em != "" else rec.get("expected_margin"),
                    "updated_at":      ist_now().isoformat(),
                })
                self._repo.save_all_raw(records)
                self._invalidate()
                return rec
        return None

    def delete(self, cid: str) -> bool:
        """Delete by id.  Returns True if found and deleted."""
        records     = self._repo.get_all_raw()
        new_records = [r for r in records if r.get("id") != cid]
        if len(new_records) == len(records):
            return False
        self._repo.save_all_raw(new_records)
        self._invalidate()
        return True

    # ── Discovery ─────────────────────────────────────────────────────────────

    def _get_storage(self):
        """Return the storage provider (lazy-imports to avoid circular deps)."""
        if self._storage is not None:
            return self._storage
        from backend.storage import get_provider
        return get_provider()

    def scan_discovered_offers(
        self,
        available_dates: list,
        raw_path_fn=None,   # kept for backward-compat; ignored when storage is set
    ) -> dict:
        """
        Scan all raw parquet files via StorageProvider and return a dict:
          {offer_id: {offer_name, publisher_ids: set, game_type_guess}}
        Errors on individual files are silently skipped.
        """
        storage = self._get_storage()
        offers: dict = {}

        def _norm(v):
            try:
                return str(int(float(v)))
            except (ValueError, TypeError):
                return str(v).strip()

        for date in available_dates:
            try:
                if not storage.raw_day_exists(date):
                    continue
                sub = storage.load_raw_day(date, columns=["offer", "offerName", "partner"])
                if sub.empty:
                    continue
                sub = sub.dropna().drop_duplicates()
                sub["_oid"] = sub["offer"].map(_norm)
                sub = sub[sub["_oid"] != ""]

                for oid, grp in sub.groupby("_oid", sort=False):
                    oname = str(grp["offerName"].iloc[0]).strip()
                    pubs  = set(grp["partner"].astype(str).str.strip().tolist())
                    if oid not in offers:
                        offers[oid] = {
                            "offer_name":      oname,
                            "publisher_ids":   set(),
                            "game_type_guess": "CPE" if "cpe" in oname.lower() else "CPI",
                        }
                    offers[oid]["publisher_ids"] |= pubs
            except Exception:
                pass
        return offers

    def get_discovered(self, available_dates: list, raw_path_fn=None) -> list:
        """Return list of every offer seen in raw data, annotated with configured status."""
        offers  = self.scan_discovered_offers(available_dates)
        configs = self._repo.get_all_raw()
        cfg_map = {c["offer_id"]: c["id"] for c in configs}

        result = []
        for oid, info in sorted(offers.items(), key=lambda x: x[1]["offer_name"].lower()):
            result.append({
                "offer_id":        oid,
                "offer_name":      info["offer_name"],
                "publisher_ids":   sorted(info["publisher_ids"]),
                "game_type_guess": info["game_type_guess"],
                "configured":      oid in cfg_map,
                "config_id":       cfg_map.get(oid),
            })
        return result

    def get_unconfigured(self, available_dates: list, raw_path_fn=None) -> dict:
        """Return only offers that exist in raw data but have no game config."""
        offers  = self.scan_discovered_offers(available_dates)
        configs = self._repo.get_all_raw()
        cfg_ids = {str(c.get("offer_id", "")).strip() for c in configs}

        result = []
        for oid, info in sorted(offers.items(), key=lambda x: x[1]["offer_name"].lower()):
            if oid not in cfg_ids:
                result.append({
                    "offer_id":        oid,
                    "offer_name":      info["offer_name"],
                    "publisher_ids":   sorted(info["publisher_ids"]),
                    "game_type_guess": info["game_type_guess"],
                })
        return {"unconfigured": result, "count": len(result)}

    def get_status(
        self,
        available_dates: list,
        raw_path_fn=None,   # kept for backward-compat; ignored
        publisher_count: int = 0,
    ) -> dict:
        """Dashboard summary counts for the Game Configurations admin tab."""
        configs = self._repo.get_all_raw()
        offers  = self.scan_discovered_offers(available_dates)

        configured_ids = {c["offer_id"] for c in configs}
        pending_count  = sum(1 for oid in offers if oid not in configured_ids)

        def _has_kpi(c):
            pk = c.get("publisher_kpi") or {}
            ck = c.get("client_kpi")    or {}
            return bool(pk.get("retention") or pk.get("roas") or
                        ck.get("retention") or ck.get("roas"))

        return {
            "publishers_count": publisher_count,
            "discovered_count": len(offers),
            "configured_count": len(configs),
            "pending_count":    pending_count,
            "missing_kpi":      sum(1 for c in configs if not _has_kpi(c)),
            "missing_funnel":   sum(1 for c in configs if not c.get("expected_funnel")),
            "missing_margin":   sum(1 for c in configs if c.get("expected_margin") is None),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _invalidate(self) -> None:
        """Evict all config-derived cache entries after a write."""
        self._cache.evict(*_CACHE_KEYS)


class _Conflict(Exception):
    """Raised when a duplicate key constraint is violated."""
    pass


# Re-export so routes can catch it
Conflict = _Conflict
