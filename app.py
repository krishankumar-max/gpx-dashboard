"""
Sapphyre Analytics Dashboard — Flask backend.

Run:
    python app.py
    # or, for production:
    flask run --host=0.0.0.0 --port=5000
"""

import datetime as dt
import sys
import threading
import time
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify
from flask_cors import CORS
from loguru import logger

# ── Project root on path so backend.* imports resolve ─────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.aggregator import load_summary, upsert_day
from backend.config import (
    ADMIN_KEY, CACHE_BACKEND, CORS_ORIGINS,
    REPO_BACKEND, SECRET_KEY, STORAGE_BACKEND, SYNC_DAY_WORKERS,
)
from backend.fetcher import fetch_day_sync
from backend.repositories import RepositoryFactory
from backend.repositories.cache import CacheFactory, DictCache
from backend.services import build_services
from backend.storage import load_day, save_day
from backend.storage import set_provider as _set_storage_provider
from backend.storage.factory import StorageFactory

# ── Timezone constant ──────────────────────────────────────────────────────────
_IST = "Asia/Kolkata"
_IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))

def ist_today() -> dt.date:
    """Return the current calendar date in Asia/Kolkata (IST).

    Always use this instead of dt.date.today() for business-day calculations.
    dt.date.today() returns the server's local date, which is wrong on UTC hosts
    during the 18:30–23:59 UTC window (= 00:00–05:29 IST the next IST day).
    """
    return dt.datetime.now(_IST_TZ).date()

# ── Config storage (local-JSON mode) ──────────────────────────────────────────
# Ensure data/config/ exists for JSON-backend repositories.
# Skipped in S3-only deployments where this directory is irrelevant,
# but safe to create regardless (parents=True, exist_ok=True).
_CONFIG_DIR = ROOT / "data" / "config"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ── Initialize PostgreSQL (when REPO_BACKEND=pg) ──────────────────────────────
if REPO_BACKEND == "pg":
    from backend.repositories.pg.db import init_db as _init_db
    _init_db()  # creates tables via SQLAlchemy metadata if they don't exist

# ── Initialize repositories (wired at module load, not request time) ───────────
_game_config_repo = RepositoryFactory.create_game_config_repo(REPO_BACKEND)
_publisher_repo   = RepositoryFactory.create_publisher_repo(REPO_BACKEND)
_partner_repo     = RepositoryFactory.create_partner_repo(REPO_BACKEND)


# ── Wire storage provider (Strategy pattern — swap local ↔ S3 via env var) ─────
_set_storage_provider(StorageFactory.create(STORAGE_BACKEND))


# ── Background sync state ──────────────────────────────────────────────────────
_sync_lock = threading.Lock()
_agg_lock  = threading.Lock()   # serialises concurrent upsert_day() calls

_sync_state: dict = {
    "running":      False,
    "log":          [],
    "progress":     0,           # days fully completed
    "total":        0,           # total days requested
    "error":        None,
    "finished":     False,
    "summary":      {},
    # Granular per-day progress (updated by page callback)
    "active_dates": {},          # { "YYYY-MM-DD": {pages_done, pages_total, rows} }
}


def _sync_log(msg: str) -> None:
    with _sync_lock:
        _sync_state["log"].append(msg)
    logger.info(msg)


def _do_sync(
    from_date: dt.date,
    to_date: dt.date,
    publisher_ids: set[str],
    partner_names: dict[str, str] | None = None,
) -> None:
    """
    High-speed parallel sync engine.

    Architecture
    ────────────
    • Outer pool: SYNC_DAY_WORKERS days in parallel.
    • Inner pool (inside fetch_day_sync): SYNC_WORKERS page-threads per day.
    • Each day independently: fetch → dedup → merge → publisher-filter → save → validate.
    • Aggregate writes serialised with _agg_lock (single daily_summary.parquet).
    • _sync_state updated from all threads under _sync_lock.
    • Browser-independent: runs as a non-daemon OS thread.

    publisher_ids  : set of string publisher IDs — always from Management, never None/empty.
    partner_names  : {publisher_id: partner_name} — used for human-readable log labels.

    Performance (typical)
    ──────────────────────
    SYNC_PAGE_SIZE=2000, SYNC_WORKERS=40, SYNC_DAY_WORKERS=2
      150k rows/day → 75 pages → 2 parallel rounds of 40 ≈ 2-4 s/day
      22 days in parallel pairs → ~25 s total
    """
    _pnames: dict[str, str] = partner_names or {}
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    # Build ordered date list
    dates: list[dt.date] = []
    cur = from_date
    while cur <= to_date:
        dates.append(cur)
        cur += dt.timedelta(days=1)

    # Convert publisher IDs to integers (Sapphyre API expects ints)
    pid_list: list[int] | None = None
    if publisher_ids:
        converted = []
        for p in publisher_ids:
            try:
                converted.append(int(p))
            except ValueError:
                logger.warning(f"Non-numeric publisher ID ignored: {p!r}")
        pid_list = converted if converted else None

    # ── Initialise state ───────────────────────────────────────────────────────
    with _sync_lock:
        _sync_state.update(
            running=True, log=[], progress=0, total=len(dates),
            error=None, finished=False, summary={}, active_dates={},
        )

    if pid_list:
        _pub_labels = [
            f"{_pnames.get(str(p), 'Unknown')} ({p})"
            for p in sorted(pid_list)
        ]
        pub_note_lines = ["Using publishers:"] + [f"  • {lbl}" for lbl in _pub_labels]
    else:
        pub_note_lines = ["⚠ No publishers configured — fetching ALL partners"]

    # ── Record sync start in SyncHistory (PostgreSQL mode, best-effort) ────────
    _sh_id: str | None = None
    if REPO_BACKEND == "pg":
        try:
            import uuid as _uuid
            from backend.repositories.pg.db     import get_session as _sh_get_session
            from backend.repositories.pg.schema import SyncHistoryORM
            _sh_id = str(_uuid.uuid4())
            _sh_started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with _sh_get_session() as _sh_sess:
                _sh_sess.add(SyncHistoryORM(
                    id=_sh_id,
                    started_at=_sh_started,
                    status="running",
                    date_from=from_date.isoformat(),
                    date_to=to_date.isoformat(),
                ))
        except Exception as _sh_err:
            logger.warning(f"SyncHistory: failed to record start — {_sh_err}")
            _sh_id = None

    _sync_log(f"Sync started  {from_date} → {to_date}  "
              f"({len(dates)} day(s), {SYNC_DAY_WORKERS} parallel)")
    for line in pub_note_lines:
        _sync_log(line)

    # Shared cumulative counters (written under _sync_lock)
    _counters = {
        "downloaded": 0, "inserted": 0, "updated": 0,
        "skipped": 0, "days_done": 0,
    }
    start_time = time.time()

    # ── Per-day worker ─────────────────────────────────────────────────────────
    def _process_day(date: dt.date) -> dict:
        """
        Fetch → dedup → merge → save one day.
        Returns a stats dict.  Raises on unrecoverable error.
        """
        date_str = date.isoformat()

        # Register this date as active
        with _sync_lock:
            _sync_state["active_dates"][date_str] = {
                "pages_done": 0, "pages_total": 0, "rows": 0,
            }

        # Progress callback: called every 10 pages from inside fetch_day_sync
        def _on_page(pages_done: int, pages_total: int, rows_so_far: int) -> None:
            with _sync_lock:
                _sync_state["active_dates"][date_str] = {
                    "pages_done":  pages_done,
                    "pages_total": pages_total,
                    "rows":        rows_so_far,
                }

        # ── Fetch (streaming: pages flushed to callback as they arrive) ──────
        _day_labels = [
            f"{_pnames.get(str(p), 'Unknown')} ({p})"
            for p in sorted(pid_list)
        ]
        _sync_log(f"[{date}] → Using publishers: {', '.join(_day_labels)}")
        _is_live = (date == ist_today())
        if _is_live:
            _sync_log(f"[{date}] Live data window detected. Validation bypassed.")

        # Streaming accumulator: each flushed batch becomes a DataFrame chunk.
        # Keeps peak RAM bounded to ~1 batch in the fetcher + growing DataFrame here.
        _chunks: list[pd.DataFrame] = []

        def _on_rows_ready(batch: list[dict]) -> None:
            if not batch:
                return
            _chunks.append(pd.DataFrame(batch))

        fetch_day_sync(
            date,
            partner_ids=pid_list,
            on_page_done=_on_page,
            on_rows_ready=_on_rows_ready,
            is_live=_is_live,
        )

        if not _chunks:
            return {"downloaded": 0, "inserted": 0, "updated": 0, "skipped": 0}

        # Build the full DataFrame from chunks — more memory-efficient than
        # pd.DataFrame(list_of_180k_dicts) because each chunk was already
        # freed from the fetcher's pending buffer before we get here.
        new_df = pd.concat(_chunks, ignore_index=True)
        _chunks.clear()   # release chunk references

        # ── Dedup within incoming batch ────────────────────────────────────
        skipped = 0
        if "_id" in new_df.columns:
            before = len(new_df)
            new_df = new_df.drop_duplicates(subset=["_id"], keep="last")
            skipped = before - len(new_df)
            if skipped:
                _sync_log(f"[{date}] {skipped} intra-batch dupes removed")

        downloaded = len(new_df)
        _sync_log(f"[{date}] ✓ Downloaded {downloaded:,} rows")

        # ── Merge with existing parquet ────────────────────────────────────
        existing = load_day(date)
        if existing.empty:
            inserted, updated = len(new_df), 0
            final_df = new_df
        else:
            if "_id" in new_df.columns and "_id" in existing.columns:
                ex_ids  = set(existing["_id"].dropna())
                in_ids  = set(new_df["_id"].dropna())
                updated  = len(in_ids & ex_ids)
                inserted = len(in_ids - ex_ids)
            else:
                inserted, updated = len(new_df), 0
            merged   = pd.concat([existing, new_df], ignore_index=True)
            if "_id" in merged.columns:
                merged = merged.drop_duplicates(subset=["_id"], keep="last")
            final_df = merged

        # ── Defensive publisher filter ─────────────────────────────────────
        # This is the critical safety gate.  It runs EVERY time before saving,
        # catching two failure modes:
        #   1. Sapphyre returns unexpected publishers despite the API filter.
        #   2. The existing parquet contains rows from a previous unfiltered
        #      sync; the merge above would re-include them without this guard.
        #
        # configured_str is built from pid_list (which is always non-None here
        # because api_sync_start blocks sync when publisher_ids is empty).
        configured_str: set[str] = {str(p) for p in (pid_list or [])}
        if not configured_str:
            # Should never happen — api_sync_start blocks empty publisher lists —
            # but guard here in case _do_sync is ever called programmatically.
            _sync_log(
                f"[{date}] ⚠ configured_str is empty (all IDs non-numeric?); "
                "skipping save to avoid writing unfiltered data"
            )
            with _sync_lock:
                _sync_state["active_dates"].pop(date_str, None)
            return {
                "downloaded": downloaded,
                "inserted": 0, "updated": 0, "skipped": downloaded,
            }
        if "partner" in final_df.columns:
            # Cast to str so integers and string IDs both match.
            partner_str = final_df["partner"].astype(str)
            mask        = partner_str.isin(configured_str)
            rejected    = final_df[~mask]
            if not rejected.empty:
                bad_pubs = sorted(partner_str[~mask].unique().tolist())
                _sync_log(
                    f"[{date}] ⚠ PUBLISHER FILTER: removed {len(rejected):,} rows "
                    f"from unconfigured publishers {bad_pubs}"
                )
                final_df = final_df[mask].reset_index(drop=True)
                if final_df.empty:
                    _sync_log(
                        f"[{date}] ⚠ No rows remain after publisher filter — skipping save"
                    )
                    with _sync_lock:
                        _sync_state["active_dates"].pop(date_str, None)
                    return {
                        "downloaded": downloaded,
                        "inserted": 0, "updated": 0, "skipped": downloaded,
                    }

        # ── Save parquet (each date has its own file → no conflict) ───────
        save_day(date, final_df.to_dict("records"))

        # ── Post-save publisher validation ─────────────────────────────────
        # Confirm that what landed in the file exactly matches the configured
        # publisher set.  The defensive filter above should guarantee this;
        # this check makes any breach immediately visible in the sync log.
        if "partner" in final_df.columns:
            saved_pubs = sorted(final_df["partner"].astype(str).unique().tolist())
            saved_labels = [
                f"{_pnames.get(p, 'Unknown')} ({p})"
                for p in saved_pubs
            ]
            _sync_log(f"[{date}] ✓ Saved publishers: {saved_labels}")
            unexpected = [p for p in saved_pubs if p not in configured_str]
            if unexpected:
                _sync_log(
                    f"[{date}] ⚠ VALIDATION FAILED: unexpected publishers in saved data: "
                    f"{unexpected}  — these should have been removed by the publisher filter"
                )

        # ── Aggregate (single shared file → serialise with _agg_lock) ─────
        with _agg_lock:
            upsert_day(date)
        _CACHE.clear()

        _sync_log(
            f"[{date}] ✓ Saved  inserted={inserted:,}  "
            f"updated={updated:,}  total_in_file={len(final_df):,}"
        )

        # Mark date inactive
        with _sync_lock:
            _sync_state["active_dates"].pop(date_str, None)

        return {
            "downloaded": downloaded, "inserted": inserted,
            "updated": updated,       "skipped": skipped,
        }

    # ── Outer parallel day pool ────────────────────────────────────────────────
    day_workers = min(len(dates), SYNC_DAY_WORKERS)
    try:
        with ThreadPoolExecutor(max_workers=day_workers) as outer:
            future_map = {
                outer.submit(_process_day, d): d for d in dates
            }
            for future in _as_completed(future_map):
                date = future_map[future]
                try:
                    stats = future.result()
                except Exception as exc:
                    _sync_log(f"✗ [{date}] FAILED: {exc}")
                    stats = {"downloaded": 0, "inserted": 0,
                             "updated": 0, "skipped": 0}

                with _sync_lock:
                    _counters["downloaded"] += stats["downloaded"]
                    _counters["inserted"]   += stats["inserted"]
                    _counters["updated"]    += stats["updated"]
                    _counters["skipped"]    += stats["skipped"]
                    _counters["days_done"]  += 1
                    _sync_state["progress"]  = _counters["days_done"]
                    # Live summary visible mid-sync
                    _sync_state["summary"] = {
                        "dates_processed": _counters["days_done"],
                        "publishers":      len(pid_list) if pid_list else 0,
                        "rows_downloaded": _counters["downloaded"],
                        "rows_inserted":   _counters["inserted"],
                        "rows_updated":    _counters["updated"],
                        "rows_skipped":    _counters["skipped"],
                        "duration_seconds": round(time.time() - start_time),
                        "duration_str":     "",
                    }

        # ── Final summary ──────────────────────────────────────────────────
        duration = round(time.time() - start_time)
        mins, secs = divmod(duration, 60)
        dur_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        final_summary = {
            "dates_processed": len(dates),
            "publishers":      len(pid_list) if pid_list else 0,
            "rows_downloaded": _counters["downloaded"],
            "rows_inserted":   _counters["inserted"],
            "rows_updated":    _counters["updated"],
            "rows_skipped":    _counters["skipped"],
            "duration_seconds": duration,
            "duration_str":     dur_str,
        }

        _sync_log("──────────────────────────────────────────")
        _sync_log(f"✓ Sync complete  ({dur_str})")
        _sync_log(f"  Dates       : {len(dates)}")
        _sync_log(f"  Publishers  : {len(pid_list) if pid_list else 'all'}")
        _sync_log(f"  Downloaded  : {_counters['downloaded']:,}")
        _sync_log(f"  Inserted    : {_counters['inserted']:,}")
        _sync_log(f"  Updated     : {_counters['updated']:,}")
        _sync_log(f"  Skipped     : {_counters['skipped']:,}")

        with _sync_lock:
            _sync_state.update(
                running=False, finished=True,
                active_dates={}, summary=final_summary,
            )

        # ── Record sync success in SyncHistory (best-effort) ──────────────────
        if REPO_BACKEND == "pg" and _sh_id:
            try:
                from backend.repositories.pg.db     import get_session as _sh_get_session
                from backend.repositories.pg.schema import SyncHistoryORM
                _sh_finished = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with _sh_get_session() as _sh_sess:
                    _sh_row = _sh_sess.get(SyncHistoryORM, _sh_id)
                    if _sh_row:
                        _sh_row.finished_at = _sh_finished
                        _sh_row.status      = "success"
                        _sh_row.rows_synced = _counters["downloaded"]
            except Exception as _sh_err:
                logger.warning(f"SyncHistory: failed to record success — {_sh_err}")

    except Exception as exc:
        duration = round(time.time() - start_time)
        _sync_log(f"✗ Sync engine failed: {exc}")
        with _sync_lock:
            _sync_state.update(
                running=False, error=str(exc), finished=True,
                active_dates={},
                summary={
                    "dates_processed": _counters["days_done"],
                    "publishers":      len(pid_list) if pid_list else 0,
                    "rows_downloaded": _counters["downloaded"],
                    "rows_inserted":   _counters["inserted"],
                    "rows_updated":    _counters["updated"],
                    "rows_skipped":    _counters["skipped"],
                    "duration_seconds": duration,
                    "duration_str":     f"{duration}s",
                },
            )

        # ── Record sync failure in SyncHistory (best-effort) ──────────────────
        if REPO_BACKEND == "pg" and _sh_id:
            try:
                from backend.repositories.pg.db     import get_session as _sh_get_session
                from backend.repositories.pg.schema import SyncHistoryORM
                _sh_finished = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with _sh_get_session() as _sh_sess:
                    _sh_row = _sh_sess.get(SyncHistoryORM, _sh_id)
                    if _sh_row:
                        _sh_row.finished_at = _sh_finished
                        _sh_row.status      = "failed"
                        _sh_row.rows_synced = _counters["downloaded"]
                        _sh_row.error       = str(exc)
            except Exception as _sh_err:
                logger.warning(f"SyncHistory: failed to record failure — {_sh_err}")


# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/static",
)
CORS(app, origins=CORS_ORIGINS)  # restricted to CORS_ORIGINS (see backend/config.py)
app.config["SECRET_KEY"] = SECRET_KEY

# ── In-memory summary cache (DictCache with per-key TTL) ───────────────────────
# Phase 2: replaced bare dict with DictCache(CacheProvider).
# _CACHE kept as an alias so the one direct reference in _process_day
# (_CACHE.clear()) compiles unchanged.
_CACHE_TTL: int = 300          # summary DataFrame TTL — 5 minutes
_DATES_TTL: int = 30           # available_dates() TTL — 30 seconds
_CFG_TTL:   int = 60           # game config JSON TTL — 60 seconds

_cache: DictCache = CacheFactory.create(CACHE_BACKEND)  # type: ignore[assignment]
_CACHE = _cache   # backward-compat alias (used by _process_day: _CACHE.clear())

# ── Phase 3: Service layer ─────────────────────────────────────────────────────
# Services own all business logic.  Routes call services; services call repos.
# Re-use the already-registered storage provider (set at line ~113 above).
from backend.storage import get_provider as _get_storage_provider
_storage_provider = _get_storage_provider()

(
    _game_config_svc,
    _publisher_svc,
    _partner_svc,
    _funnel_svc,
    _analytics_svc,
    _sync_svc,
) = build_services(
    cache=_cache,
    game_config_repo=_game_config_repo,
    publisher_repo=_publisher_repo,
    partner_repo=_partner_repo,
    storage=_storage_provider,
    sync_day_workers=SYNC_DAY_WORKERS,
    sync_shared_state=_sync_state,
    sync_shared_lock=_sync_lock,
)


# ── Attach services + shared objects to the Flask app ─────────────────────────
# Blueprint route handlers access these via current_app.<name> (deps.py).
app.analytics_svc    = _analytics_svc    # type: ignore[attr-defined]
app.game_config_svc  = _game_config_svc  # type: ignore[attr-defined]
app.publisher_svc    = _publisher_svc    # type: ignore[attr-defined]
app.partner_svc      = _partner_svc      # type: ignore[attr-defined]
app.funnel_svc       = _funnel_svc       # type: ignore[attr-defined]
app.sync_svc         = _sync_svc         # type: ignore[attr-defined]
app.sync_engine      = _do_sync          # type: ignore[attr-defined]
app.cache            = _cache            # type: ignore[attr-defined]


# ── Register blueprints ────────────────────────────────────────────────────────
from backend.routes import register_blueprints
register_blueprints(app)


# ── Global error handlers ──────────────────────────────────────────────────────

@app.errorhandler(404)
def _not_found(e):
    return jsonify({"error": "not found"}), 404


@app.errorhandler(405)
def _method_not_allowed(e):
    return jsonify({"error": "method not allowed"}), 405


@app.errorhandler(500)
def _internal_error(e):
    logger.exception("Unhandled exception")
    return jsonify({"error": "internal server error"}), 500


# ── Run ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Sapphyre Analytics on http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001, use_reloader=True)
