"""
S3Storage — StorageProvider backed by Amazon S3.

S3 key layout
-------------
    s3://<bucket>/raw/YYYY-MM-DD.parquet
    s3://<bucket>/aggregated/daily_summary.parquet
    s3://<bucket>/exports/
    s3://<bucket>/uploads/

Configuration
-------------
Set the following environment variables (or .env):
    STORAGE_BACKEND=s3
    S3_BUCKET=your-bucket-name
    AWS_REGION=ap-south-1         (or your region)

Authentication (choose one):
    - IAM Instance Profile on EC2 (recommended for production — no keys needed)
    - AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY environment variables
    - ~/.aws/credentials file

Requires:
    boto3      — S3 list/delete operations
    s3fs       — PyArrow-compatible filesystem for Parquet I/O
    pyarrow    — already a project dependency
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import s3fs
from loguru import logger

from backend.config import KEEP_COLS, AGG_GROUP_COLS
from backend.storage.base import StorageProvider


# ── Parquet schema (identical to LocalStorage — ensures file compatibility) ───

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
    table   = pa.Table.from_pandas(df, preserve_index=False)
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


class S3Storage(StorageProvider):
    """
    Amazon S3 backed StorageProvider.

    All Parquet I/O uses s3fs + PyArrow so the API is identical to
    LocalStorage.  Business logic does not need to change.

    For bulk operations (list / delete), boto3 is used directly because
    s3fs does not expose batch deletes efficiently.
    """

    def __init__(
        self,
        bucket: str,
        region: str = "ap-south-1",
        raw_prefix: str = "raw/",
        agg_prefix: str = "aggregated/",
    ) -> None:
        if not bucket:
            raise ValueError(
                "S3Storage requires a non-empty bucket name. "
                "Set the S3_BUCKET environment variable."
            )
        self._bucket      = bucket
        self._region      = region
        self._raw_prefix  = raw_prefix.rstrip("/") + "/"
        self._agg_prefix  = agg_prefix.rstrip("/") + "/"
        self._summary_key = f"{self._agg_prefix}daily_summary.parquet"

        # Lazy-initialised clients
        self.__fs: s3fs.S3FileSystem | None = None
        self.__s3: Any = None

        logger.info(
            f"S3Storage initialised — bucket={bucket!r} region={region!r}"
        )

    # ── Client accessors (lazy init so tests can patch) ───────────────────────

    @property
    def _fs(self) -> s3fs.S3FileSystem:
        if self.__fs is None:
            self.__fs = s3fs.S3FileSystem(
                anon=False,
                client_kwargs={"region_name": self._region},
            )
        return self.__fs

    @property
    def _s3(self):
        if self.__s3 is None:
            self.__s3 = boto3.client("s3", region_name=self._region)
        return self.__s3

    # ── Key helpers ───────────────────────────────────────────────────────────

    def _raw_key(self, date: dt.date) -> str:
        return f"{self._raw_prefix}{date.isoformat()}.parquet"

    def _raw_uri(self, date: dt.date) -> str:
        return f"s3://{self._bucket}/{self._raw_key(date)}"

    def _summary_uri(self) -> str:
        return f"s3://{self._bucket}/{self._summary_key}"

    # ── Raw day I/O ───────────────────────────────────────────────────────────

    def load_raw_day(
        self,
        date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        uri = self._raw_uri(date)
        try:
            kwargs: dict = {}
            if columns:
                kwargs["columns"] = columns
            return pq.read_table(uri, filesystem=self._fs, **kwargs).to_pandas()
        except FileNotFoundError:
            logger.warning(f"[{date}] S3 raw file not found: {uri}")
            return pd.DataFrame(columns=columns if columns else KEEP_COLS)
        except Exception as exc:
            logger.error(f"[{date}] Failed to load from S3: {exc}")
            return pd.DataFrame(columns=columns if columns else KEEP_COLS)

    def save_raw_day(self, date: dt.date, df: pd.DataFrame) -> None:
        if df.empty:
            logger.info(f"[{date}] No rows to save — skipping S3 write.")
            return
        df    = _coerce_raw_df(df)
        table = _cast_to_raw_schema(df)
        uri   = self._raw_uri(date)
        pq.write_table(table, uri, filesystem=self._fs, compression="snappy")
        logger.success(f"[{date}] Saved {len(df):,} rows → {uri}")

    def raw_day_exists(self, date: dt.date) -> bool:
        try:
            return self._fs.exists(f"{self._bucket}/{self._raw_key(date)}")
        except Exception:
            return False

    def delete_raw_day(self, date: dt.date) -> None:
        key = self._raw_key(date)
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
            logger.info(f"[{date}] Deleted S3 raw file: s3://{self._bucket}/{key}")
        except Exception as exc:
            logger.warning(f"[{date}] Could not delete s3://{self._bucket}/{key}: {exc}")

    def load_raw_range(
        self,
        from_date: dt.date,
        to_date: dt.date,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        current = from_date
        while current <= to_date:
            if self.raw_day_exists(current):
                df = self.load_raw_day(current, columns=columns)
                if not df.empty:
                    frames.append(df)
            current += dt.timedelta(days=1)
        if not frames:
            return pd.DataFrame(columns=columns if columns else KEEP_COLS)
        return pd.concat(frames, ignore_index=True)

    def available_dates(self) -> list[dt.date]:
        """List all raw/*.parquet keys and parse dates from filenames."""
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            pages     = paginator.paginate(
                Bucket=self._bucket,
                Prefix=self._raw_prefix,
            )
            dates: list[dt.date] = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    filename = key.split("/")[-1]  # e.g. "2026-01-01.parquet"
                    if filename.endswith(".parquet"):
                        stem = filename[:-8]       # strip ".parquet"
                        try:
                            dates.append(dt.date.fromisoformat(stem))
                        except ValueError:
                            pass
            return sorted(dates)
        except Exception as exc:
            logger.error(f"S3Storage.available_dates failed: {exc}")
            return []

    # ── Aggregated summary I/O ────────────────────────────────────────────────

    def load_summary(self) -> pd.DataFrame:
        _summary_cols = AGG_GROUP_COLS + [
            "revenue", "payout", "conversions", "valid_conversions", "unique_installs"
        ]
        uri = self._summary_uri()
        try:
            df = pq.read_table(uri, filesystem=self._fs).to_pandas()
        except FileNotFoundError:
            logger.warning(
                f"S3 daily_summary.parquet not found — run a sync first. "
                f"Expected at: {uri}"
            )
            return pd.DataFrame(columns=_summary_cols)
        except Exception as exc:
            logger.error(f"Failed to load summary from S3: {exc}")
            return pd.DataFrame(columns=_summary_cols)

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
        df    = df.sort_values(AGG_GROUP_COLS).reset_index(drop=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        uri   = self._summary_uri()
        pq.write_table(table, uri, filesystem=self._fs, compression="snappy")
        logger.info(f"S3Storage: saved aggregated summary → {uri} ({len(df):,} rows)")

    def summary_exists(self) -> bool:
        try:
            return self._fs.exists(f"{self._bucket}/{self._summary_key}")
        except Exception:
            return False

    # ── Bulk-delete ───────────────────────────────────────────────────────────

    def delete_all_raw(self) -> int:
        """Delete all raw/*.parquet objects from S3.  Returns count deleted."""
        try:
            paginator = self._s3.get_paginator("list_objects_v2")
            pages     = paginator.paginate(
                Bucket=self._bucket,
                Prefix=self._raw_prefix,
            )
            to_delete: list[dict] = []
            for page in pages:
                for obj in page.get("Contents", []):
                    to_delete.append({"Key": obj["Key"]})

            if not to_delete:
                return 0

            # S3 batch delete: max 1000 per request
            deleted = 0
            for i in range(0, len(to_delete), 1000):
                batch = to_delete[i : i + 1000]
                self._s3.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": batch, "Quiet": True},
                )
                deleted += len(batch)

            logger.info(f"S3Storage: deleted {deleted} raw parquet object(s).")
            return deleted
        except Exception as exc:
            logger.error(f"S3Storage.delete_all_raw failed: {exc}")
            return 0

    def delete_summary(self) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=self._summary_key)
            logger.info(f"S3Storage: deleted summary → s3://{self._bucket}/{self._summary_key}")
        except Exception as exc:
            logger.warning(f"S3Storage.delete_summary: {exc}")
