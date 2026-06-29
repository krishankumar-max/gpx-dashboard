"""
SyncService — controls the parallel day-sync engine.

Owns:
  - start(from_date, to_date) — validates, builds publisher set, fires thread
  - get_status()              — returns snapshot of sync state
  - clear()                   — resets state between runs

The engine itself (_do_sync) remains in app.py for now (it closes over
_agg_lock, upsert_day, load_day, save_day which live at module level).
SyncService is the thin interface layer routes call instead of reaching
into app.py's module-level state directly.
"""
from __future__ import annotations

import datetime as dt
import threading
import time

import pandas as pd

from backend.repositories.base import PublisherRepository
from backend.repositories.cache import CacheProvider
from backend.utils import ist_today


class SyncService:
    """
    Interface to the parallel sync engine.

    The heavy lifting (_do_sync body) stays in app.py because it directly
    imports load_day / save_day / upsert_day from backend.aggregator.

    This service owns validation and the clear() contract so that routes
    remain thin.  State is stored in a shared dict that app.py also writes
    to from the _do_sync thread — both sides hold a reference to the same
    object.

    Usage
    -----
    # In app.py, after creating _sync_state and _sync_lock:
    _sync_svc = SyncService(
        publisher_repo=_publisher_repo,
        cache=_cache,
        shared_state=_sync_state,
        shared_lock=_sync_lock,
    )
    """

    def __init__(
        self,
        publisher_repo:   PublisherRepository,
        cache:            CacheProvider,
        sync_day_workers: int = 2,
        shared_state:     dict | None = None,
        shared_lock:      threading.Lock | None = None,
    ) -> None:
        self._pub_repo    = publisher_repo
        self._cache       = cache
        self._day_workers = sync_day_workers

        # If the caller provides a shared state dict (app.py's _sync_state),
        # use it directly so both _do_sync and the service read the same data.
        if shared_state is not None:
            self._state = shared_state
            self._lock  = shared_lock or threading.Lock()
        else:
            self._lock  = threading.Lock()
            self._state = {
                "running":      False,
                "log":          [],
                "progress":     0,
                "total":        0,
                "error":        None,
                "finished":     False,
                "summary":      {},
                "active_dates": {},
            }

    # ── State accessors ────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return a shallow copy of current sync state (thread-safe)."""
        with self._lock:
            return dict(self._state)

    def get_status(self) -> dict:
        return self.get_state()

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._state.get("running"))

    # ── Business logic ────────────────────────────────────────────────────────

    def validate_start(self, from_date: dt.date, to_date: dt.date) -> tuple[set[str], dict[str, str]]:
        """
        Validate a sync request.

        Returns
        -------
        (publisher_ids, partner_names)

        Raises
        ------
        RuntimeError   — sync already running
        ValueError     — invalid date range or no publishers configured
        """
        if self.is_running():
            raise RuntimeError("Sync is already running")

        if from_date > to_date:
            raise ValueError("from_date must be <= to_date")

        today = ist_today()
        if from_date > today:
            raise ValueError(f"from_date {from_date} is in the future")

        publishers = self._pub_repo.get_all_raw()
        if not publishers:
            raise ValueError(
                "No publishers configured. "
                "Add publishers via Management → Publishers before syncing."
            )

        publisher_ids: set[str] = set()
        partner_names: dict[str, str] = {}
        for p in publishers:
            pid = str(p.get("publisher_id", "")).strip()
            if pid:
                publisher_ids.add(pid)
                partner_names[pid] = str(p.get("partner_name", "Unknown")).strip()

        if not publisher_ids:
            raise ValueError(
                "No publisher IDs found in publisher records. "
                "Ensure each publisher has a numeric publisher_id."
            )

        return publisher_ids, partner_names

    def clear(self) -> dict:
        """
        Reset sync state.  Cannot clear while a sync is running.

        Returns the cleared state dict.
        Raises RuntimeError if called while running.
        """
        with self._lock:
            if self._state.get("running"):
                raise RuntimeError("Cannot clear while sync is running")
            self._state.update(
                running=False, log=[], progress=0, total=0,
                error=None, finished=False, summary={}, active_dates={},
            )
            return dict(self._state)

    def invalidate_cache(self) -> None:
        """Evict analytics cache after sync completes a day."""
        self._cache.clear()
