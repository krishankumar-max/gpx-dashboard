#!/usr/bin/env python
"""
Local scheduler — runs sync_sapphyre.py every 6 hours.

Usage:
    python scripts/run_every_6_hours.py

Keep this process running (e.g., in a tmux session or as a system service).
The scheduler syncs the last 2 days on each run to handle late-arriving data.

On first run, it performs an immediate sync so you don't have to wait 6 hours.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
from loguru import logger


# ── Config ────────────────────────────────────────────────────────────────────

# How many days back to sync on each scheduled run
SYNC_DAYS_PER_RUN: int = 2

# Interval between syncs (hours)
SYNC_INTERVAL_HOURS: int = 6

# Path to the sync script (relative to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync_sapphyre.py"


# ── Sync job ──────────────────────────────────────────────────────────────────

def run_sync() -> None:
    """Execute the sync script as a subprocess."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{now}] Starting scheduled sync (last {SYNC_DAYS_PER_RUN} days)…")

    cmd = [
        sys.executable,
        str(SYNC_SCRIPT),
        "--days-back", str(SYNC_DAYS_PER_RUN),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=False,   # let output flow to terminal
            check=False,
        )
        if result.returncode == 0:
            logger.success(f"[{now}] Sync completed successfully.")
        else:
            logger.error(
                f"[{now}] Sync exited with code {result.returncode}. "
                "Check logs/sync.log for details."
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[{now}] Failed to launch sync process: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
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
        str(PROJECT_ROOT / "logs" / "scheduler.log"),
        rotation="10 MB",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
    )

    logger.info(
        f"Scheduler started. Will sync every {SYNC_INTERVAL_HOURS} hours. "
        "Press Ctrl+C to stop."
    )

    # Run once immediately on startup
    run_sync()

    # Schedule subsequent runs
    schedule.every(SYNC_INTERVAL_HOURS).hours.do(run_sync)

    logger.info(
        f"Next run at: "
        f"{schedule.next_run().strftime('%Y-%m-%d %H:%M:%S')}"  # type: ignore[union-attr]
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # check every 30 seconds
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")


if __name__ == "__main__":
    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
    main()
