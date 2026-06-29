"""
Parquet-based storage layer.

Each calendar date is stored as a single Parquet file:
    data/raw/YYYY-MM-DD.parquet

Schema is enforced on write so downstream code can rely on types.
"""

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger

from backend.config import RAW_DIR, KEEP_COLS


# ── Schema ────────────────────────────────────────────────────────────────────
# Explicit types make Parquet files smaller and faster to read.

_SCHEMA = pa.schema(
    [
        pa.field("_id", pa.string()),
        pa.field("partnerValid", pa.bool_()),
        pa.field("valid", pa.bool_()),
        pa.field("capValid", pa.bool_()),
        pa.field("goal", pa.string()),
        pa.field("cid", pa.string()),
        pa.field("country", pa.string()),
        pa.field("state", pa.string()),
        pa.field("city", pa.string()),
        pa.field("offer", pa.string()),
        pa.field("partner", pa.string()),
        pa.field("advertiser", pa.string()),
        pa.field("time", pa.string()),  # stored as string; parsed by dashboard
        pa.field("errors", pa.list_(pa.string())),
        pa.field("payout", pa.float64()),
        pa.field("revenue", pa.float64()),
        pa.field("payoutBackup", pa.float64()),
        pa.field("revenueBackup", pa.float64()),
        pa.field("currency", pa.string()),
        pa.field("offerName", pa.string()),
        pa.field("advertiserName", pa.string()),
    ]
)


# ── Path helpers ──────────────────────────────────────────────────────────────

def raw_path(date: dt.date) -> Path:
    """Return the Parquet file path for a given date."""
    return RAW_DIR / f"{date.isoformat()}.parquet"


# ── Write ─────────────────────────────────────────────────────────────────────

def save_day(date: dt.date, rows: list[dict[str, Any]]) -> Path:
    """
    Convert *rows* to a DataFrame and write to Parquet.

    Returns the path written to.
    """
    if not rows:
        logger.info(f"[{date}] No rows to save — skipping write.")
        return raw_path(date)

    df = pd.DataFrame(rows)

    # Ensure all KEEP_COLS exist (fill missing with None)
    for col in KEEP_COLS:
        if col not in df.columns:
            df[col] = None

    df = df[KEEP_COLS]  # enforce column order

    # Coerce numeric columns; non-numeric values become NaN
    for col in ("payout", "revenue", "payoutBackup", "revenueBackup"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Coerce boolean columns
    for col in ("partnerValid", "valid", "capValid"):
        df[col] = df[col].apply(
            lambda v: bool(v) if v is not None else False
        )

    # errors column might be None or a list
    df["errors"] = df["errors"].apply(
        lambda v: v if isinstance(v, list) else ([] if v is None else [str(v)])
    )

    # Convert to PyArrow Table with schema cast
    table = pa.Table.from_pandas(df, preserve_index=False)

    # Cast each column individually to handle schema mismatches gracefully
    casted_arrays = []
    for field in _SCHEMA:
        col_name = field.name
        if col_name in table.schema.names:
            try:
                casted_arrays.append(table.column(col_name).cast(field.type))
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                # Fall back to storing as string on cast failure
                casted_arrays.append(
                    table.column(col_name).cast(pa.string())
                )
        else:
            # Column missing entirely — fill with null
            casted_arrays.append(
                pa.array([None] * len(table), type=field.type)
            )

    table = pa.table(
        {field.name: arr for field, arr in zip(_SCHEMA, casted_arrays)}
    )

    path = raw_path(date)
    pq.write_table(table, path, compression="snappy")
    logger.success(f"[{date}] Saved {len(rows):,} rows → {path}")
    return path


# ── Read ──────────────────────────────────────────────────────────────────────

def load_day(date: dt.date) -> pd.DataFrame:
    """Load raw Parquet for one date. Returns empty DataFrame if missing."""
    path = raw_path(date)
    if not path.exists():
        logger.warning(f"[{date}] Raw file not found: {path}")
        return pd.DataFrame(columns=KEEP_COLS)
    return pq.read_table(path).to_pandas()


def load_date_range(
    from_date: dt.date,
    to_date: dt.date,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Load and concatenate raw Parquet files for dates in [from_date, to_date].
    Missing dates are silently skipped.

    Parameters
    ----------
    columns : list[str] | None
        When provided, only these columns are read from each Parquet file.
        Reduces I/O significantly for callers that need only a subset of the
        21-column schema (e.g. funnel builder needs only 5 columns).
    """
    frames: list[pd.DataFrame] = []
    current = from_date
    while current <= to_date:
        path = raw_path(current)
        if path.exists():
            frames.append(pq.read_table(str(path), columns=columns).to_pandas())
        current += dt.timedelta(days=1)

    if not frames:
        return pd.DataFrame(columns=columns if columns else KEEP_COLS)

    return pd.concat(frames, ignore_index=True)


def available_dates() -> list[dt.date]:
    """Return sorted list of dates that have raw Parquet files."""
    dates = []
    for p in sorted(RAW_DIR.glob("*.parquet")):
        try:
            dates.append(dt.date.fromisoformat(p.stem))
        except ValueError:
            pass
    return dates
