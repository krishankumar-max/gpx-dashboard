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


def is_configured(record: dict) -> bool:
    """Return True iff a game config record is fully configured.

    A record is *not* configured when ``campaign_status == "pending"`` —
    i.e. it is an auto-seeded stub created by seed_from_sync() that the
    admin has not yet reviewed.

    This is the single canonical definition used throughout the codebase.
    Import this function instead of repeating the string literal.
    """
    return record.get("campaign_status") != "pending"


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
        """Return only fully-configured (non-pending) game config records.

        Pending stubs created by seed_from_sync() are intentionally excluded
        here — they belong in the Unconfigured Games list, not the Configured
        Games table, so the two sections are mutually exclusive.
        """
        return [r for r in self._repo.get_all_raw() if is_configured(r)]

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
        """
        Update a game config by id.  Returns updated dict or None if not found.

        Uses repo.update() (per-record) instead of save_all_raw() (full replace)
        to avoid the delete-everything-then-reinsert pattern on PostgreSQL.

        Updatable fields include offer_name and campaign_status so Game
        Configurations is the single place an admin edits all game metadata.
        When the admin saves a pending record with any real data, they should
        also set campaign_status to something other than "pending" (e.g. "live")
        to make it visible on dashboards.
        """
        existing = self._repo.get_by_id(cid)
        if existing is None:
            return None

        rec = existing.to_dict() if hasattr(existing, "to_dict") else dict(existing)
        em  = body.get("expected_margin")

        # Build the merged record — body values win; missing keys fall back to rec
        merged = dict(rec)
        merged.update({
            "offer_name":      str(body.get("offer_name", rec.get("offer_name", ""))).strip()
                               or rec.get("offer_name", ""),
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

        # campaign_status: allow explicit update (drives dashboard visibility)
        if "campaign_status" in body:
            merged["campaign_status"] = body["campaign_status"]

        result = self._repo.update(cid, merged)
        self._invalidate()
        return result

    def delete(self, cid: str) -> bool:
        """Delete by id.  Returns True if found and deleted."""
        deleted = self._repo.delete(cid)
        if deleted:
            self._invalidate()
        return deleted

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

    def seed_from_sync(self, available_dates: list) -> int:
        """
        Auto-insert a pending Game Configuration stub for every offer discovered
        in raw data that does not yet have a config record.

        Called automatically at the end of each sync run.  This ensures:
          - Every discovered offer appears in Administration → Game Configurations
          - New offers are marked campaign_status="pending" (hidden from dashboards)
          - Existing configs (pending or live) are never overwritten
          - No duplicates are created

        Returns the number of new stubs created.
        """
        import uuid as _uuid

        offers     = self.scan_discovered_offers(available_dates)
        if not offers:
            return 0

        existing   = self._repo.get_all_raw()
        known_oids = {str(c.get("offer_id", "")).strip() for c in existing}

        created = 0
        for oid, info in sorted(offers.items()):
            if oid in known_oids:
                continue  # config already exists — never overwrite
            stub = {
                "id":              str(_uuid.uuid4()),
                "offer_id":        oid,
                "offer_name":      info["offer_name"],
                "game_type":       info.get("game_type_guess", "CPI"),
                "payable_goals":   [],
                "publisher_kpi":   {"retention": [], "roas": []},
                "client_kpi":      {"retention": [], "roas": []},
                "expected_funnel": [],
                "expected_margin": None,
                "campaign_status": "pending",   # hidden from dashboards
                "configured_at":   ist_now().isoformat(),
            }
            try:
                self._repo.create(stub)
                known_oids.add(oid)   # prevent duplicates within this batch
                created += 1
            except Exception:
                pass  # concurrent write or unique-constraint violation — safe to skip

        if created:
            self._invalidate()
        return created

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
        """
        Return offers that need admin attention:
          - Discovered in raw data with no config record at all (edge case after seeding)
          - Discovered in raw data with a config record in status "pending"
            (auto-seeded by seed_from_sync but not yet reviewed by admin)

        These are the items the admin sees in the "Unconfigured Games" panel.
        Setting campaign_status to anything other than "pending" (e.g. "live")
        removes the offer from this list and makes it visible on dashboards.
        """
        offers    = self.scan_discovered_offers(available_dates)
        configs   = self._repo.get_all_raw()
        cfg_by_oid = {str(c.get("offer_id", "")).strip(): c for c in configs}

        result = []
        for oid, info in sorted(offers.items(), key=lambda x: x[1]["offer_name"].lower()):
            cfg = cfg_by_oid.get(oid)
            # Include if no config at all, or config is still pending
            if cfg is None or cfg.get("campaign_status") == "pending":
                result.append({
                    "offer_id":        oid,
                    "offer_name":      info["offer_name"],
                    "publisher_ids":   sorted(info["publisher_ids"]),
                    "game_type_guess": info["game_type_guess"],
                    "config_id":       cfg.get("id") if cfg else None,
                })
        return {"unconfigured": result, "count": len(result)}

    def get_status(
        self,
        available_dates: list,
        raw_path_fn=None,   # kept for backward-compat; ignored
        publisher_count: int = 0,
    ) -> dict:
        """Dashboard summary counts for the Game Configurations admin tab."""
        real_configs   = self.list()                            # canonical: non-pending only
        offers         = self.scan_discovered_offers(available_dates)

        configured_ids = {c["offer_id"] for c in real_configs}
        # "pending_count" = discovered offers not yet in configured_ids
        pending_count  = sum(1 for oid in offers if oid not in configured_ids)

        def _has_kpi(c):
            pk = c.get("publisher_kpi") or {}
            ck = c.get("client_kpi")    or {}
            return bool(pk.get("retention") or pk.get("roas") or
                        ck.get("retention") or ck.get("roas"))

        return {
            "publishers_count": publisher_count,
            "discovered_count": len(offers),
            "configured_count": len(real_configs),
            "pending_count":    pending_count,
            "missing_kpi":      sum(1 for c in real_configs if not _has_kpi(c)),
            "missing_funnel":   sum(1 for c in real_configs if not c.get("expected_funnel")),
            "missing_margin":   sum(1 for c in real_configs if c.get("expected_margin") is None),
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
