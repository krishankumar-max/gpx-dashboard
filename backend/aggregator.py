"""
Aggregation layer.

Reads raw Parquet via the active StorageProvider, computes a daily summary,
and persists it back via the same provider.

The aggregation logic (groupby, unique_installs, valid_conversions) is
completely unchanged from the original implementation.  Only the I/O layer
has been updated to use the StorageProvider interface instead of hardcoded
filesystem paths, making it compatible with both LocalStorage and S3Storage.

Summary schema (daily_summary.parquet)
---------------------------------------
date             : str  (YYYY-MM-DD)
partner          : str
offerName        : str
goal             : str
revenue          : float
payout           : float
conversions      : int   (total rows in that group)
valid_conversions : int  (rows where valid == True)
unique_installs  : int   (COUNT DISTINCT cid for install goals)
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from loguru import logger

from backend.config import AGG_GROUP_COLS
from backend.storage import get_provider


# ── Internal aggregation logic (UNCHANGED) ────────────────────────────────────

def _summarise_day(df: pd.DataFrame, date: dt.date) -> pd.DataFrame:
    """
    Aggregate one day's raw DataFrame into summary rows.
    Returns an empty DataFrame if the input is empty.
    """
    _cols = AGG_GROUP_COLS + [
        "revenue", "payout", "conversions", "valid_conversions", "unique_installs"
    ]
    if df.empty:
        return pd.DataFrame(columns=_cols)

    df = df.copy()

    # Convert UTC timestamps to IST before any aggregation
    if "time" in df.columns:
        df["time"] = (
            pd.to_datetime(df["time"], utc=True, errors="coerce")
            .dt.tz_convert("Asia/Kolkata")
        )

    df["date"] = date.isoformat()
    df["conversions"] = 1  # each row = one conversion event

    for col in ("revenue", "payout"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["valid_conversions"] = df["valid"].apply(lambda v: 1 if v is True else 0)

    for col in ("partner", "offerName", "goal"):
        df[col] = df[col].fillna("Unknown").astype(str)

    summary = (
        df.groupby(AGG_GROUP_COLS, dropna=False)
        .agg(
            revenue=("revenue", "sum"),
            payout=("payout", "sum"),
            conversions=("conversions", "sum"),
            valid_conversions=("valid_conversions", "sum"),
        )
        .reset_index()
    )

    # unique_installs: COUNT(DISTINCT cid) per group for install-type goals
    install_mask = (
        df["goal"].str.lower().str.contains("install", na=False) | (df["goal"] == "1")
    )
    unique_inst = (
        df[install_mask]
        .groupby(AGG_GROUP_COLS, dropna=False)
        .agg(unique_installs=("cid", "nunique"))
        .reset_index()
    )
    summary = summary.merge(unique_inst, on=AGG_GROUP_COLS, how="left")
    summary["unique_installs"] = summary["unique_installs"].fillna(0).astype(int)
    return summary


# ── Public API ────────────────────────────────────────────────────────────────

def rebuild_aggregates() -> None:
    """
    Rebuild the daily_summary from scratch using all available raw files.
    Use after a full historical sync or data correction.
    """
    storage = get_provider()
    dates   = storage.available_dates()

    if not dates:
        logger.warning("No raw files found — nothing to aggregate.")
        return

    logger.info(f"Rebuilding aggregates from {len(dates)} day(s)...")
    frames: list[pd.DataFrame] = []
    for date in dates:
        df = storage.load_raw_day(date)
        summary = _summarise_day(df, date)
        if not summary.empty:
            frames.append(summary)

    if not frames:
        logger.warning("All raw files were empty — nothing aggregated.")
        return

    combined = pd.concat(frames, ignore_index=True)
    storage.save_summary(combined)
    logger.success(f"Rebuilt daily_summary — {len(combined):,} rows.")


def upsert_day(date: dt.date) -> None:
    """
    Incrementally update the daily_summary for a single *date*.

    Algorithm:
      1. Load existing summary (if any).
      2. Drop all rows for *date*.
      3. Compute fresh summary rows for *date* from raw data.
      4. Concatenate and save.

    Type contract:
      load_summary() returns date as datetime.date (for range comparisons).
      _summarise_day() returns date as str (date.isoformat()).
      save_summary() normalises date → str before writing to Parquet so the
      stored type is always consistent regardless of the caller's type.
      The filter here compares datetime.date == datetime.date (not str).
    """
    storage  = get_provider()
    df_raw   = storage.load_raw_day(date)
    new_rows = _summarise_day(df_raw, date)

    if storage.summary_exists():
        existing = storage.load_summary()
        # existing["date"] is datetime.date (load_summary converts from parquet string).
        # Compare datetime.date to datetime.date — NOT to date.isoformat() (str),
        # which would always evaluate to True and never remove the current day's rows.
        existing = existing[existing["date"] != date]
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows

    # Diagnostic: log schema and a sample date value so type mismatches are
    # visible in the log before PyArrow sees them.
    logger.debug(f"[{date}] save_summary dtypes:\n{combined.dtypes.to_string()}")
    if "date" in combined.columns and len(combined) > 0:
        _sample = combined["date"].iloc[0]
        logger.debug(
            f"[{date}] date column sample: {_sample!r}  "
            f"python_type={type(_sample).__name__}"
        )

    storage.save_summary(combined)
    logger.success(
        f"[{date}] Aggregates updated — {len(new_rows)} summary rows."
    )


def load_summary() -> pd.DataFrame:
    """
    Load the pre-aggregated summary.
    Thin wrapper kept for backward compatibility with existing callers.
    """
    return get_provider().load_summary()
