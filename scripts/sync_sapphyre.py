#!/usr/bin/env python
"""
Sync script — fetches postback data from Sapphyre and stores it locally.

Usage examples
--------------
# Sync the last 7 days (default):
    python scripts/sync_sapphyre.py

# Sync a specific date:
    python scripts/sync_sapphyre.py --date 2026-06-01

# Sync a date range:
    python scripts/sync_sapphyre.py --from-date 2026-05-01 --to-date 2026-06-01

# Sync N days back from today:
    python scripts/sync_sapphyre.py --days-back 30

# Rebuild the aggregated summary after syncing:
    python scripts/sync_sapphyre.py --rebuild-agg
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

# Add project root to sys.path so imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from backend.config import SYNC_DAYS_BACK
from backend.fetcher import fetch_day_sync
from backend.storage import save_day
from backend.aggregator import upsert_day, rebuild_aggregates


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Sapphyre postback data to local Parquet files."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        help="Sync a single date (YYYY-MM-DD).",
    )
    group.add_argument(
        "--days-back",
        type=int,
        default=None,
        help=f"Sync this many days back from today (default: {SYNC_DAYS_BACK}).",
    )
    parser.add_argument(
        "--from-date",
        type=dt.date.fromisoformat,
        default=None,
        help="Start of date range (YYYY-MM-DD). Use with --to-date.",
    )
    parser.add_argument(
        "--to-date",
        type=dt.date.fromisoformat,
        default=None,
        help="End of date range (YYYY-MM-DD). Use with --from-date.",
    )
    parser.add_argument(
        "--rebuild-agg",
        action="store_true",
        help="Rebuild daily_summary.parquet from scratch after syncing.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip dates that already have a raw Parquet file.",
    )
    return parser.parse_args()


# ── Core sync logic ───────────────────────────────────────────────────────────

def sync_dates(
    dates: list[dt.date],
    skip_existing: bool = False,
) -> list[dt.date]:
    """
    Sync each date sequentially (parallelism is inside fetch_day_sync per page).
    Returns the list of dates actually synced.
    """
    from backend.storage import raw_path  # local import avoids circular reference

    synced: list[dt.date] = []
    failed: list[dt.date] = []

    for date in dates:
        if skip_existing and raw_path(date).exists():
            logger.info(f"[{date}] Already synced — skipping.")
            continue

        try:
            logger.info(f"[{date}] Starting sync…")
            rows = fetch_day_sync(date)
            save_day(date, rows)
            upsert_day(date)
            synced.append(date)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[{date}] Sync failed: {exc}")
            failed.append(date)

    if failed:
        logger.warning(f"Failed dates: {[str(d) for d in failed]}")
    return synced


def build_date_list(args: argparse.Namespace) -> list[dt.date]:
    """Determine which dates to sync from CLI arguments."""
    today = dt.date.today()

    if args.date:
        return [args.date]

    if args.from_date and args.to_date:
        if args.from_date > args.to_date:
            raise ValueError("--from-date must be <= --to-date")
        dates = []
        cur = args.from_date
        while cur <= args.to_date:
            dates.append(cur)
            cur += dt.timedelta(days=1)
        return dates

    days = args.days_back if args.days_back is not None else SYNC_DAYS_BACK
    return [today - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # Configure loguru — pretty output to console
    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{message}</cyan>"
        ),
        level="INFO",
        colorize=True,
    )
    logger.add(
        "logs/sync.log",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
        encoding="utf-8",
    )

    try:
        dates = build_date_list(args)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info(
        f"Syncing {len(dates)} date(s): "
        f"{dates[0].isoformat()} → {dates[-1].isoformat()}"
    )

    synced = sync_dates(dates, skip_existing=args.skip_existing)

    if args.rebuild_agg:
        logger.info("Rebuilding full aggregated summary…")
        rebuild_aggregates()

    logger.success(
        f"Done. Synced {len(synced)}/{len(dates)} date(s) successfully."
    )


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    main()
