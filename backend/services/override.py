"""
OverrideService — business logic for manual revenue / cost overrides.

Responsibilities
----------------
- CRUD: list, upsert (create-or-update), delete
- get_override_map(): build the lookup dict consumed by AnalyticsService
- Cache invalidation: evict "edf" (enriched DataFrame) after every mutation
  so the analytics pipeline immediately reflects the change.

Override lookup key: (date_str "YYYY-MM-DD", publisher_id, offer_id)
At most ONE override per key — enforced by the repository upsert().
"""
from __future__ import annotations

import uuid
import datetime as dt

from backend.repositories.base import OverrideRepository
from backend.utils import ist_now


class OverrideService:
    """Business logic for manual override records."""

    def __init__(self, repo: OverrideRepository, cache) -> None:
        self._repo  = repo
        self._cache = cache   # CacheProvider — used to evict "edf" on mutation

    # ── Queries ────────────────────────────────────────────────────────────────

    def list(self) -> list[dict]:
        """Return all overrides, newest first."""
        return self._repo.get_all()

    def get_by_id(self, override_id: str) -> dict | None:
        return self._repo.get_by_id(override_id)

    def get_override_map(self) -> dict[tuple, dict]:
        """
        Return a lookup dict for the analytics injection layer.

        Format:
            {
                ("2024-07-01", "12345", "offer_abc"): {
                    "revenue": 150.0,   # None if not overriding revenue
                    "cost":    45.0,    # None if not overriding cost
                },
                ...
            }

        Only entries that have at least one non-None override value are included.
        """
        result: dict[tuple, dict] = {}
        for rec in self._repo.get_all():
            rev  = rec.get("revenue_override")
            cost = rec.get("cost_override")
            if rev is None and cost is None:
                continue   # nothing to override
            key = (
                str(rec.get("date", "")),
                str(rec.get("publisher_id", "")),
                str(rec.get("offer_id", "")),
            )
            result[key] = {"revenue": rev, "cost": cost}
        return result

    # ── Mutations ──────────────────────────────────────────────────────────────

    def upsert(self, body: dict) -> dict:
        """
        Create or update the override for (date, publisher_id, offer_id).

        Required body keys:
            date, publisher_id, offer_id

        Optional:
            publisher_name, offer_name, revenue_override, cost_override,
            reason, notes, created_by

        Returns the saved record.
        Raises ValueError on validation failures.
        """
        date = str(body.get("date", "")).strip()
        publisher_id = str(body.get("publisher_id", "")).strip()
        offer_id     = str(body.get("offer_id", "")).strip()

        if not date:
            raise ValueError("date is required")
        if not publisher_id:
            raise ValueError("publisher_id is required")
        if not offer_id:
            raise ValueError("offer_id is required")

        # Validate date format
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            raise ValueError(f"Invalid date format: {date!r}. Expected YYYY-MM-DD.")

        # Parse optional numeric overrides
        revenue_override = _parse_optional_float(body.get("revenue_override"), "revenue_override")
        cost_override    = _parse_optional_float(body.get("cost_override"),    "cost_override")

        now = ist_now().isoformat()

        # Check for existing record to preserve id + created_at
        existing = self._repo.get_by_key(date, publisher_id, offer_id)

        record = {
            "id":               existing["id"] if existing else str(uuid.uuid4()),
            "date":             date,
            "publisher_id":     publisher_id,
            "publisher_name":   str(body.get("publisher_name", "") or "").strip(),
            "offer_id":         offer_id,
            "offer_name":       str(body.get("offer_name", "") or "").strip(),
            "revenue_override": revenue_override,
            "cost_override":    cost_override,
            "reason":           str(body.get("reason", "") or "").strip() or None,
            "notes":            str(body.get("notes", "") or "").strip() or None,
            "created_at":       existing["created_at"] if existing else now,
            "updated_at":       now,
            "created_by":       body.get("created_by") or (existing or {}).get("created_by"),
        }

        saved = self._repo.upsert(record)
        self._evict_analytics_cache()
        return saved

    def delete(self, override_id: str) -> bool:
        """
        Delete an override by id.

        Returns True if found and deleted.
        Raises ValueError if not found.
        """
        rec = self._repo.get_by_id(override_id)
        if rec is None:
            raise ValueError(f"Override {override_id!r} not found")
        result = self._repo.delete(override_id)
        if result:
            self._evict_analytics_cache()
        return result

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _evict_analytics_cache(self) -> None:
        """Evict the enriched DataFrame cache so analytics immediately reflect the change."""
        try:
            self._cache.evict("edf")
        except Exception:
            pass  # best-effort — never crash on cache eviction


def _parse_optional_float(value, field_name: str) -> float | None:
    """Parse a nullable float field.  Returns None if value is None/empty-string."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field_name} must be a number, got {value!r}")
    if f < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return f
