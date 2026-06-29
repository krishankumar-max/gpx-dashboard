"""
StorageProvider — abstract interface for analytics data storage.

Implementations
---------------
LocalStorage  — reads/writes Parquet files on the local filesystem (default)
S3Storage     — reads/writes Parquet files on Amazon S3

Business logic (aggregator, sync, route handlers) never imports an
implementation directly.  All callers depend only on this interface,
which means switching from local → S3 is a one-line config change.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

import pandas as pd


class StorageProvider(ABC):
    """Abstract base class for raw + aggregated Parquet storage."""

    # ── Raw postback files (one per calendar date) ────────────────────────────

    @abstractmethod
    def load_raw_day(
        self,
        date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Load raw postback rows for one calendar date.

        Parameters
        ----------
        date    : The IST calendar date to load.
        columns : When provided, only these columns are read (reduces I/O).

        Returns an empty DataFrame with correct columns if the file is missing.
        """

    @abstractmethod
    def save_raw_day(self, date: dt.date, df: pd.DataFrame) -> None:
        """
        Persist raw postback rows for one calendar date (full replacement).

        The entire file for *date* is replaced atomically.  Callers are
        responsible for merge + dedup before calling this.
        """

    @abstractmethod
    def raw_day_exists(self, date: dt.date) -> bool:
        """Return True if a raw file exists for *date*."""

    @abstractmethod
    def delete_raw_day(self, date: dt.date) -> None:
        """
        Delete the raw file for *date*.
        Used by admin reset endpoints.  Silent no-op if the file is missing.
        """

    @abstractmethod
    def load_raw_range(
        self,
        from_date: dt.date,
        to_date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Load and concatenate raw files for the inclusive range
        [from_date, to_date].  Missing dates are silently skipped.
        """

    @abstractmethod
    def available_dates(self) -> list[dt.date]:
        """Return sorted list of dates that have raw files."""

    # ── Aggregated summary (single dataset, rebuilt after each sync) ──────────

    @abstractmethod
    def load_summary(self) -> pd.DataFrame:
        """
        Load the pre-aggregated daily_summary dataset.
        Returns an empty DataFrame with correct columns if not yet created.
        """

    @abstractmethod
    def save_summary(self, df: pd.DataFrame) -> None:
        """Persist the aggregated daily_summary dataset (full replacement)."""

    @abstractmethod
    def summary_exists(self) -> bool:
        """Return True if an aggregated summary file exists."""

    # ── Bulk-delete (used by admin sync/clear endpoint) ───────────────────────

    @abstractmethod
    def delete_all_raw(self) -> int:
        """
        Delete ALL raw day files.

        Returns the number of files deleted.
        Used by the sync/clear endpoint to reset all local + remote data.
        """

    @abstractmethod
    def delete_summary(self) -> None:
        """
        Delete the aggregated summary file.
        Silent no-op if it doesn't exist.
        """
