#!/usr/bin/env python
"""
Standalone fetch test — validates the fetcher against the live Sapphyre API
without writing anything to disk.

Usage
-----
    # Test yesterday (default):
    python scripts/test_fetch.py

    # Test a specific date:
    python scripts/test_fetch.py --date 2026-06-03

    # Test and also show the first N rows as a table:
    python scripts/test_fetch.py --date 2026-06-03 --show 5

Exit codes
----------
    0 — fetch succeeded and row counts match
    1 — fetch failed or row counts mismatched
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger


def parse_args() -> argparse.Namespace:
    yesterday = dt.date.today() - dt.timedelta(days=1)
    parser = argparse.ArgumentParser(
        description="Test the Sapphyre fetcher against the live API."
    )
    parser.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        default=yesterday,
        help=f"Date to fetch (YYYY-MM-DD). Default: {yesterday}",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=0,
        metavar="N",
        help="Print the first N rows as a table after fetching (default: 0).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Pretty console logging only — no file output for a test run
    logger.remove()
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{message}</cyan>"
        ),
        level="INFO",
        colorize=True,
    )

    date: dt.date = args.date
    print(f"\n{'='*60}")
    print(f"  Sapphyre Fetch Test")
    print(f"  Date : {date}")
    print(f"{'='*60}\n")

    # ── Import here so logger is configured first ─────────────────────────────
    from backend.fetcher import fetch_day_sync, _probe_total, _make_session

    # Step 1: probe total independently so we can display it before fetching
    print("Probing row count from server…")
    session = _make_session()
    try:
        expected = _probe_total(session, date)
    except Exception as exc:
        print(f"\n[FAIL] Could not reach Sapphyre API: {exc}")
        sys.exit(1)

    print(f"\n  Expected Rows : {expected:,}")

    if expected == 0:
        print("\n  No data for this date. Try a different --date.\n")
        sys.exit(0)

    # Step 2: fetch all pages
    print("\nFetching all pages…\n")
    try:
        rows = fetch_day_sync(date)
    except RuntimeError as exc:
        # Row count mismatch — fetcher already logs details
        print(f"\n[FAIL] {exc}\n")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FAIL] Unexpected error: {exc}\n")
        sys.exit(1)

    fetched = len(rows)

    print(f"\n{'='*60}")
    print(f"  Expected Rows : {expected:,}")
    print(f"  Fetched Rows  : {fetched:,}")
    print(
        f"  Result        : {'✅ PASS — counts match' if fetched == expected else '❌ FAIL — mismatch'}"
    )
    print(f"{'='*60}\n")

    # Step 3: optionally show sample rows
    if args.show > 0 and rows:
        try:
            import pandas as pd
            df = pd.DataFrame(rows).head(args.show)
            print(f"First {args.show} row(s):\n")
            with pd.option_context(
                "display.max_columns", None,
                "display.width", 120,
                "display.max_colwidth", 30,
            ):
                print(df.to_string(index=False))
            print()
        except ImportError:
            print("(Install pandas to display sample rows.)")

    sys.exit(0 if fetched == expected else 1)


if __name__ == "__main__":
    main()
