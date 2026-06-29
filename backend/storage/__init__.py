"""
backend.storage — backward-compatible public API.

All existing callers that do:

    from backend.storage import load_day, save_day, load_date_range,
                                 available_dates, raw_path

continue to work without any changes.  The implementations now delegate
to the active StorageProvider instead of being hardcoded to the filesystem.

The active provider is set once at application startup:

    from backend.storage import set_provider
    from backend.storage.factory import StorageFactory
    from backend import config

    set_provider(StorageFactory.create(config.STORAGE_BACKEND))

If set_provider() is never called (e.g. in scripts or tests), the first
call to any function lazily initialises a LocalStorage with the paths
from backend.config — identical to the old flat-module behaviour.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from backend.config import KEEP_COLS
from backend.storage.base import StorageProvider
from backend.storage.factory import StorageFactory

# ── Module-level active provider (lazy-initialised) ──────────────────────────
_provider: StorageProvider | None = None


def get_provider() -> StorageProvider:
    """
    Return the active StorageProvider.

    On the first call (if set_provider was never called), a LocalStorage is
    created using paths from backend.config.  This matches the old behaviour
    exactly, so sync scripts and tests require no changes.
    """
    global _provider
    if _provider is None:
        _provider = StorageFactory.create("local")
    return _provider


def set_provider(p: StorageProvider) -> None:
    """
    Register a StorageProvider as the active implementation.

    Call this once at application startup before any storage operations.
    """
    global _provider
    _provider = p


# ── Backward-compatible function wrappers ─────────────────────────────────────
# These have exactly the same signatures as the old backend/storage.py
# functions so every existing import site continues to work unchanged.


def load_day(
    date: dt.date,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load raw postback rows for one calendar date."""
    return get_provider().load_raw_day(date, columns=columns)


def save_day(date: dt.date, rows: list[dict[str, Any]]) -> None:
    """Save raw postback rows for one calendar date (full replacement)."""
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=KEEP_COLS)
    get_provider().save_raw_day(date, df)


def load_date_range(
    from_date: dt.date,
    to_date: dt.date,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load and concatenate raw files for [from_date, to_date]."""
    return get_provider().load_raw_range(from_date, to_date, columns=columns)


def available_dates() -> list[dt.date]:
    """Return sorted list of dates that have raw files."""
    return get_provider().available_dates()


def raw_path(date: dt.date):
    """
    Return the local filesystem Path for a raw-day file.

    Valid only when using LocalStorage — returns None for S3Storage.
    Kept for backward compatibility with code that checks path.exists().
    New code should use raw_day_exists(date) on the provider directly.
    """
    from backend.storage.local import LocalStorage
    p = get_provider()
    if isinstance(p, LocalStorage):
        return p.raw_path(date)
    return None


# ── Re-export the classes for callers that type-hint against them ─────────────
__all__ = [
    "StorageProvider",
    "StorageFactory",
    "get_provider",
    "set_provider",
    # backward-compat functions
    "load_day",
    "save_day",
    "load_date_range",
    "available_dates",
    "raw_path",
]
