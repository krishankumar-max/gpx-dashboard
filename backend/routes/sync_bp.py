"""
Sync blueprint — /api/sync/*.

Threading note:
  sync_engine() returns the _do_sync callable that is stored on the Flask app
  by app.py.  The blueprint spawns the thread; the engine function runs
  entirely inside the thread and writes to the shared _sync_state dict that
  SyncService also references (shared_state pattern).
"""
from __future__ import annotations

import logging
import threading

from flask import Blueprint, jsonify, current_app, request

from backend.routes.auth    import admin_required
from backend.routes.deps    import sync_svc, sync_engine
from backend.routes.helpers import parse_date

logger = logging.getLogger(__name__)

bp = Blueprint("sync", __name__)


@bp.route("/api/sync/start", methods=["POST"])
@admin_required
def api_sync_start():
    body      = request.get_json() or {}
    from_date = parse_date(body.get("from_date"))
    to_date   = parse_date(body.get("to_date"))

    if not from_date or not to_date:
        return jsonify({"error": "from_date and to_date are required"}), 400

    try:
        publisher_ids, partner_names = sync_svc().validate_start(from_date, to_date)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        msg = str(e)
        if "no publisher" in msg.lower():
            return jsonify({"error": "no_publishers", "message": msg}), 400
        return jsonify({"error": msg}), 400

    # Full trace log
    logger.info("━" * 55)
    logger.info("SYNC REQUESTED — publisher trace")
    logger.info(f"  Date range    : {from_date} → {to_date}")
    logger.info(f"  Publishers loaded ({len(publisher_ids)}):")
    for pid in sorted(publisher_ids):
        name  = partner_names.get(pid, "Unknown")
        label = f"{name} ({pid})" if name else f"Unknown ({pid})"
        logger.info(f"    • {label}")
    logger.info("━" * 55)

    t = threading.Thread(
        target=sync_engine(),
        args=(from_date, to_date, publisher_ids, partner_names),
        daemon=False,
        name=f"sync-{from_date}-{to_date}",
    )
    t.start()

    return jsonify({
        "status":        "started",
        "from_date":     from_date.isoformat(),
        "to_date":       to_date.isoformat(),
        "publisher_ids": sorted(publisher_ids),
        "publishers": [
            {
                "id":    pid,
                "name":  partner_names.get(pid, ""),
                "label": f"{partner_names.get(pid, 'Unknown')} ({pid})",
            }
            for pid in sorted(publisher_ids)
        ],
    })


@bp.route("/api/sync/status")
def api_sync_status():
    return jsonify(sync_svc().get_status())


@bp.route("/api/sync/clear", methods=["POST"])
@admin_required
def api_sync_clear():
    """
    Delete all raw + aggregated parquet files and flush the summary cache.
    Requires ``{"token": "DELETE"}`` in the JSON body as a safety gate.
    """
    body = request.get_json() or {}
    if body.get("token") != "DELETE":
        return jsonify({"error": "confirmation required — send token: DELETE"}), 400

    try:
        sync_svc().clear()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409

    from backend.storage import get_provider as _get_storage_provider
    storage = _get_storage_provider()
    deleted = storage.delete_all_raw()
    storage.delete_summary()

    # Flush all in-memory caches
    current_app.cache.clear()  # type: ignore[attr-defined]

    return jsonify({"status": "cleared", "files_deleted": deleted})
