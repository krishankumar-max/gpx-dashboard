"""
LocalStorage — StorageProvider backed by the local filesystem.

Parquet files are stored as:
    <raw_dir>/YYYY-MM-DD.parquet
    <agg_dir>/daily_summary.parquet

This is the default backend.  All logic that was previously in
backend/storage.py (the old flat module) now lives here.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

from backend.config import KEEP_COLS, AGG_GROUP_COLS
from backend.storage.base import StorageProvider


# ── Parquet schema (enforced on write) ───────────────────────────────────────

_RAW_SCHEMA = pa.schema(
    [
        pa.field("_id",            pa.string()),
        pa.field("partnerValid",   pa.bool_()),
        pa.field("valid",          pa.bool_()),
        pa.field("capValid",       pa.bool_()),
        pa.field("goal",           pa.string()),
        pa.field("cid",            pa.string()),
        pa.field("country",        pa.string()),
        pa.field("state",          pa.string()),
        pa.field("city",           pa.string()),
        pa.field("offer",          pa.string()),
        pa.field("partner",        pa.string()),
        pa.field("advertiser",     pa.string()),
        pa.field("time",           pa.string()),
        pa.field("errors",         pa.list_(pa.string())),
        pa.field("payout",         pa.float64()),
        pa.field("revenue",        pa.float64()),
        pa.field("payoutBackup",   pa.float64()),
        pa.field("revenueBackup",  pa.float64()),
        pa.field("currency",       pa.string()),
        pa.field("offerName",      pa.string()),
        pa.field("advertiserName", pa.string()),
    ]
)


def _cast_to_raw_schema(df: pd.DataFrame) -> pa.Table:
    """Convert a DataFrame to a PyArrow Table, casting each column individually."""
    table = pa.Table.from_pandas(df, preserve_index=False)
    casted: list[pa.Array] = []
    for field in _RAW_SCHEMA:
        if field.name in table.schema.names:
            try:
                casted.append(table.column(field.name).cast(field.type))
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                casted.append(table.column(field.name).cast(pa.string()))
        else:
            casted.append(pa.array([None] * len(table), type=field.type))
    return pa.table({f.name: arr for f, arr in zip(_RAW_SCHEMA, casted)})


def _coerce_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise types in a raw postback DataFrame before schema-casting."""
    df = df.copy()
    for col in KEEP_COLS:
        if col not in df.columns:
            df[col] = None

    df = df[KEEP_COLS]

    for col in ("payout", "revenue", "payoutBackup", "revenueBackup"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    for col in ("partnerValid", "valid", "capValid"):
        df[col] = df[col].apply(lambda v: bool(v) if v is not None else False)

    df["errors"] = df["errors"].apply(
        lambda v: v if isinstance(v, list) else ([] if v is None else [str(v)])
    )
    return df


class LocalStorage(StorageProvider):
    """Filesystem-backed StorageProvider."""

    def __init__(self, raw_dir: Path, agg_dir: Path) -> None:
        self._raw_dir = Path(raw_dir)
        self._agg_dir = Path(agg_dir)
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        self._agg_dir.mkdir(parents=True, exist_ok=True)
        self._summary_path = self._agg_dir / "daily_summary.parquet"

    # ── Path helper (exposed for backward-compat shim) ────────────────────────

    def raw_path(self, date: dt.date) -> Path:
        return self._raw_dir / f"{date.isoformat()}.parquet"

    # ── Raw day I/O ───────────────────────────────────────────────────────────

    def load_raw_day(
        self,
        date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        path = self.raw_path(date)
        if not path.exists():
            logger.warning(f"[{date}] Raw file not found: {path}")
            return pd.DataFrame(columns=columns if columns else KEEP_COLS)
        kwargs: dict[str, Any] = {}
        if columns:
            kwargs["columns"] = columns
        return pq.read_table(str(path), **kwargs).to_pandas()

    def save_raw_day(self, date: dt.date, df: pd.DataFrame) -> None:
        if df.empty:
            logger.info(f"[{date}] No rows to save — skipping write.")
            return
        df = _coerce_raw_df(df)
        table = _cast_to_raw_schema(df)
        path = self.raw_path(date)
        pq.write_table(table, path, compression="snappy")
        logger.success(f"[{date}] Saved {len(df):,} rows → {path}")

    def raw_day_exists(self, date: dt.date) -> bool:
        return self.raw_path(date).exists()

    def delete_raw_day(self, date: dt.date) -> None:
        path = self.raw_path(date)
        if path.exists():
            path.unlink()
            logger.info(f"[{date}] Deleted raw file: {path}")

    def load_raw_range(
        self,
        from_date: dt.date,
        to_date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        current = from_date
        kwargs: dict[str, Any] = {}
        if columns:
            kwargs["columns"] = columns
        while current <= to_date:
            path = self.raw_path(current)
            if path.exists():
                frames.append(pq.read_table(str(path), **kwargs).to_pandas())
            current += dt.timedelta(days=1)

        if not frames:
            return pd.DataFrame(columns=columns if columns else KEEP_COLS)
        return pd.concat(frames, ignore_index=True)

    def available_dates(self) -> list[dt.date]:
        dates: list[dt.date] = []
        for p in sorted(self._raw_dir.glob("*.parquet")):
            try:
                dates.append(dt.date.fromisoformat(p.stem))
            except ValueError:
                pass
        return dates

    # ── Aggregated summary I/O ────────────────────────────────────────────────

    def load_summary(self) -> pd.DataFrame:
        _summary_cols = AGG_GROUP_COLS + [
            "revenue", "payout", "conversions", "valid_conversions", "unique_installs"
        ]
        if not self._summary_path.exists():
            logger.warning(
                "daily_summary.parquet not found — run a sync first. "
                f"Expected at: {self._summary_path}"
            )
            return pd.DataFrame(columns=_summary_cols)

        df = pq.read_table(self._summary_path).to_pandas()

        for col in ("revenue", "payout"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        for col in ("conversions", "valid_conversions"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        if "unique_installs" not in df.columns:
            df["unique_installs"] = 0
        df["unique_installs"] = (
            pd.to_numeric(df["unique_installs"], errors="coerce").fillna(0).astype(int)
        )
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def save_summary(self, df: pd.DataFrame) -> None:
        df = df.copy()
        # Normalise the date column to str ("YYYY-MM-DD") before Arrow serialisation.
        # load_summary() converts the stored string back to datetime.date for comparisons.
        # Without this, a concat of datetime.date rows (from load_summary) with str rows
        # (from _summarise_day) produces a mixed-type object column that PyArrow cannot
        # map to a single Arrow type, raising:
        #   "object of type <class 'str'> cannot be converted to int"
        #   "Conversion failed for column date with type object"
        df["date"] = df["date"].apply(
            lambda d: d.isoformat() if isinstance(d, dt.date) else str(d)
        )
        df = df.sort_values(AGG_GROUP_COLS).reset_index(drop=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, self._summary_path, compression="snappy")
        logger.info(
            f"Saved aggregated summary → {self._summary_path} ({len(df):,} rows)"
        )

    def summary_exists(self) -> bool:
        return self._summary_path.exists()

    # ── Bulk-delete ───────────────────────────────────────────────────────────

    def delete_all_raw(self) -> int:
        deleted = 0
        for p in sorted(self._raw_dir.glob("*.parquet")):
            p.unlink()
            deleted += 1
        if deleted:
            logger.info(f"LocalStorage: deleted {deleted} raw parquet file(s).")
        return deleted

    def delete_summary(self) -> None:
        if self._summary_path.exists():
            self._summary_path.unlink()
            logger.info(f"LocalStorage: deleted summary → {self._summary_path}")
