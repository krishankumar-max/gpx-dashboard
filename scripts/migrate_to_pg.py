#!/usr/bin/env python3
"""
scripts/migrate_to_pg.py — One-time migration: JSON config files → PostgreSQL.

Run this ONCE on the production server after:
  1. PostgreSQL is running and DATABASE_URL is set in .env
  2. `alembic upgrade head` has been run (tables exist)
  3. REPO_BACKEND=pg in .env

Usage:
    cd /path/to/sapphyre-dashboard
    python scripts/migrate_to_pg.py

It reads the current JSON config files and inserts their contents into
PostgreSQL.  Existing rows are NOT overwritten — the script is safe to
re-run but will skip records that already exist (by primary key).

If you want a hard reset first:
    python scripts/migrate_to_pg.py --reset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── Make project root importable ─────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from backend.config import DATABASE_URL, DATA_DIR
from backend.repositories.pg.db import init_db, get_session
from backend.repositories.pg.schema import GameConfigORM, PublisherORM, PartnerORM


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  [SKIP] {path} not found")
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [ERROR] Failed to read {path}: {e}")
        return []


def _migrate_game_configs(session, records: list[dict], reset: bool) -> tuple[int, int]:
    if reset:
        deleted = session.query(GameConfigORM).delete()
        print(f"  [RESET] Deleted {deleted} existing game_configs rows")

    inserted = skipped = 0
    for rec in records:
        rid = rec.get("id")
        if rid and session.get(GameConfigORM, rid):
            skipped += 1
            continue
        import uuid as _uuid
        row = GameConfigORM(
            id              = rid or str(_uuid.uuid4()),
            offer_id        = str(rec.get("offer_id", "")).strip(),
            offer_name      = str(rec.get("offer_name", "")).strip(),
            game_type       = str(rec.get("game_type", "CPI")).strip(),
            payable_goals   = rec.get("payable_goals") or [],
            publisher_kpi   = rec.get("publisher_kpi") or {},
            client_kpi      = rec.get("client_kpi") or {},
            expected_funnel = rec.get("expected_funnel"),
            tracking_links  = rec.get("tracking_links") or [],
            play_store      = rec.get("play_store"),
            assets          = rec.get("assets") or [],
            expected_margin = rec.get("expected_margin"),
            campaign_status = rec.get("campaign_status"),
            platform        = rec.get("platform"),
            notes           = rec.get("notes"),
            client_notes    = rec.get("client_notes"),
            configured_at   = rec.get("configured_at"),
            updated_at      = rec.get("updated_at"),
        )
        session.add(row)
        inserted += 1
    return inserted, skipped


def _migrate_publishers(session, records: list[dict], reset: bool) -> tuple[int, int]:
    if reset:
        deleted = session.query(PublisherORM).delete()
        print(f"  [RESET] Deleted {deleted} existing publishers rows")

    inserted = skipped = 0
    for rec in records:
        rid = rec.get("id")
        if rid and session.get(PublisherORM, rid):
            skipped += 1
            continue
        import uuid as _uuid
        row = PublisherORM(
            id              = rid or str(_uuid.uuid4()),
            publisher_id    = str(rec.get("publisher_id", "")).strip(),
            partner_name    = str(rec.get("partner_name", "")).strip(),
            game_name       = str(rec.get("game_name", "")).strip(),
            game_id         = str(rec.get("game_id", "")).strip(),
            game_type       = str(rec.get("game_type", "")).strip(),
            payable_goals   = rec.get("payable_goals") or [],
            publisher_kpi   = rec.get("publisher_kpi") or {},
            client_kpi      = rec.get("client_kpi") or {},
            expected_funnel = rec.get("expected_funnel"),
            expected_margin = float(rec.get("expected_margin") or 0.0),
        )
        session.add(row)
        inserted += 1
    return inserted, skipped


def _migrate_partners(session, records: list[dict], reset: bool) -> tuple[int, int]:
    if reset:
        deleted = session.query(PartnerORM).delete()
        print(f"  [RESET] Deleted {deleted} existing partners rows")

    inserted = skipped = 0
    for rec in records:
        rid = rec.get("id")
        if rid and session.get(PartnerORM, rid):
            skipped += 1
            continue
        import uuid as _uuid
        row = PartnerORM(
            id            = rid or str(_uuid.uuid4()),
            partner_name  = str(rec.get("partner_name", "")).strip(),
            company_name  = str(rec.get("company_name", "")).strip(),
            email         = str(rec.get("email", "")).strip().lower(),
            password_hash = str(rec.get("password_hash", "")),
            status        = str(rec.get("status", "active")),
            last_login    = rec.get("last_login"),
            created_at    = rec.get("created_at"),
        )
        session.add(row)
        inserted += 1
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate JSON configs to PostgreSQL")
    parser.add_argument("--reset", action="store_true",
                        help="Delete all existing rows before inserting (hard reset)")
    args = parser.parse_args()

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set. Set it in .env or the environment.")
        sys.exit(1)

    print(f"Connecting to: {DATABASE_URL.split('@')[-1]}")  # hide credentials
    init_db(DATABASE_URL)
    print("PostgreSQL connected.\n")

    config_dir = DATA_DIR / "config"
    tables = [
        ("game_configs",  config_dir / "game_configs.json", _migrate_game_configs),
        ("publishers",    config_dir / "publishers.json",   _migrate_publishers),
        ("partners",      config_dir / "partners.json",     _migrate_partners),
    ]

    total_inserted = total_skipped = 0
    with get_session() as session:
        for table_name, path, fn in tables:
            print(f"── {table_name} ({path.name})")
            records = _load_json(path)
            print(f"  Found {len(records)} records in JSON")
            ins, skp = fn(session, records, args.reset)
            total_inserted += ins
            total_skipped  += skp
            print(f"  Inserted: {ins}  Skipped (already exists): {skp}")

    print(f"\nDone.  Total inserted: {total_inserted}  Total skipped: {total_skipped}")
    print("\nVerify with:")
    print("  psql $DATABASE_URL -c 'SELECT count(*) FROM game_configs;'")
    print("  psql $DATABASE_URL -c 'SELECT count(*) FROM publishers;'")
    print("  psql $DATABASE_URL -c 'SELECT count(*) FROM partners;'")


if __name__ == "__main__":
    main()
