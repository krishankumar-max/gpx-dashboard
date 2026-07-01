"""
Publisher Structures blueprint.

Endpoints
---------
GET  /api/structures/publishers                  — all publishers + structure stats
GET  /api/structures/publisher/<publisher_id>    — games + versions for one publisher
GET  /api/structures/<sid>                       — single structure record
GET  /api/structures/<sid>/csv                   — download structure as CSV file

POST /api/structures                             — create new structure (JSON)
POST /api/structures/from-csv                    — create from CSV upload
POST /api/structures/clone                       — clone any version to any publisher+game
POST /api/structures/<sid>/make-live             — promote to live (auto-pauses current live)
POST /api/structures/<sid>/pause                 — pause a structure

Auth: all GET endpoints are open; all POST endpoints require @admin_required.
"""
from __future__ import annotations

import json as _json

from flask import Blueprint, Response, jsonify, request

from backend.routes.auth import admin_required
from backend.routes.deps import publisher_svc, structure_svc

bp = Blueprint("structures", __name__)


# ── Publishers list (left panel) ───────────────────────────────────────────────

@bp.route("/api/structures/publishers")
def api_structures_publishers():
    """
    Return every publisher annotated with structure-count stats.

    Merges publishers.json for names with per-publisher stats from the
    structure repo.  Publishers with no structures are included (stats = 0).
    """
    pubs      = publisher_svc().list()
    stats_map = structure_svc().stats_by_publisher()

    result = []
    for pub in pubs:
        pid  = str(pub.get("publisher_id", "")).strip()
        stat = stats_map.get(pid, {
            "live_games": 0, "pending_structures": 0,
            "paused_structures": 0, "total_structures": 0,
        })
        result.append({
            "publisher_id":       pid,
            "partner_name":       pub.get("partner_name", pid),
            "enabled":            pub.get("enabled", True),
            "live_games":         stat["live_games"],
            "pending_structures": stat["pending_structures"],
            "paused_structures":  stat["paused_structures"],
            "total_structures":   stat["total_structures"],
        })

    # Sort: publishers with structures first, then alphabetical by name
    result.sort(key=lambda p: (-p["total_structures"], p["partner_name"].lower()))
    return jsonify(result)


# ── Publisher games + history (right panel) ────────────────────────────────────

@bp.route("/api/structures/publisher/<publisher_id>")
def api_structures_publisher(publisher_id: str):
    """
    Return all games + structure versions for a publisher, grouped by offer.

    Response:
    {
      "publisher_id": "...",
      "partner_name": "...",
      "games": [
        {
          "offer_id":       "...",
          "offer_name":     "...",
          "live_structure": {...} | null,
          "versions":       [ ...sorted by version asc ]
        }
      ]
    }
    """
    structs = structure_svc().list_for_publisher(publisher_id)

    # Resolve display name
    pubs      = publisher_svc().list()
    pub_rec   = next(
        (p for p in pubs if str(p.get("publisher_id", "")) == publisher_id), None
    )
    partner_name = pub_rec.get("partner_name", publisher_id) if pub_rec else publisher_id

    # Group by offer_id
    games_map: dict[str, dict] = {}
    for s in structs:
        oid = s.get("offer_id", "")
        if oid not in games_map:
            games_map[oid] = {
                "offer_id":       oid,
                "offer_name":     s.get("offer_name", oid),
                "live_structure": None,
                "versions":       [],
            }
        games_map[oid]["versions"].append(s)
        if s.get("status") == "live":
            games_map[oid]["live_structure"] = s

    # Sort versions within each game
    for g in games_map.values():
        g["versions"].sort(key=lambda s: s.get("version", 0))

    return jsonify({
        "publisher_id": publisher_id,
        "partner_name": partner_name,
        "games": sorted(games_map.values(), key=lambda g: g["offer_name"].lower()),
    })


# ── Single structure ───────────────────────────────────────────────────────────

@bp.route("/api/structures/<sid>")
def api_structures_get(sid: str):
    record = structure_svc().get_by_id(sid)
    if record is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(record)


# ── CSV download ───────────────────────────────────────────────────────────────

@bp.route("/api/structures/<sid>/csv")
def api_structures_csv(sid: str):
    svc    = structure_svc()
    record = svc.get_by_id(sid)
    if record is None:
        return jsonify({"error": "not found"}), 404

    csv_text = svc.to_csv(sid)
    offer    = record.get("offer_name", "structure").replace(" ", "_")
    pub_id   = record.get("publisher_id", "pub")
    version  = record.get("version", 1)
    filename = f"{pub_id}_{offer}_v{version}.csv"

    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Create (JSON body) ─────────────────────────────────────────────────────────

@bp.route("/api/structures", methods=["POST"])
@admin_required
def api_structures_create():
    body = request.get_json() or {}
    try:
        record = structure_svc().create(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 201


# ── Create from CSV ────────────────────────────────────────────────────────────

@bp.route("/api/structures/from-csv", methods=["POST"])
@admin_required
def api_structures_from_csv():
    """
    Accepts:
      • multipart/form-data  — file field + form fields
      • application/json     — {csv_text, publisher_id, offer_id, ...}

    Form / JSON fields:
      publisher_id   required
      offer_id       required
      offer_name     optional
      tracking_link  optional
      preview_url    optional
      iap_events     optional (JSON-encoded list or comma-separated string)
    """
    if request.content_type and "multipart" in request.content_type:
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "file is required"}), 400
        csv_text      = f.read().decode("utf-8", errors="replace")
        publisher_id  = (request.form.get("publisher_id", "")).strip()
        offer_id      = (request.form.get("offer_id", "")).strip()
        offer_name    = (request.form.get("offer_name", "")).strip()
        tracking_link = (request.form.get("tracking_link", "")).strip()
        preview_url   = (request.form.get("preview_url", "")).strip()
        iap_raw       = request.form.get("iap_events", "[]")
        try:
            iap_events = _json.loads(iap_raw)
        except Exception:
            iap_events = [e.strip() for e in iap_raw.split(",") if e.strip()]
    else:
        body          = request.get_json() or {}
        csv_text      = body.get("csv_text", "")
        publisher_id  = str(body.get("publisher_id", "")).strip()
        offer_id      = str(body.get("offer_id", "")).strip()
        offer_name    = str(body.get("offer_name", "")).strip()
        tracking_link = str(body.get("tracking_link", "")).strip()
        preview_url   = str(body.get("preview_url", "")).strip()
        iap_events    = body.get("iap_events", [])

    if not publisher_id or not offer_id:
        return jsonify({"error": "publisher_id and offer_id are required"}), 400
    if not csv_text.strip():
        return jsonify({"error": "CSV content is empty"}), 400

    try:
        record = structure_svc().from_csv(
            csv_text, publisher_id, offer_id,
            offer_name, tracking_link, preview_url, iap_events,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(record), 201


# ── Clone ──────────────────────────────────────────────────────────────────────

@bp.route("/api/structures/clone", methods=["POST"])
@admin_required
def api_structures_clone():
    """
    Clone any structure version to a target publisher+game.

    Body: {source_id, target_publisher_id, target_offer_id, target_offer_name?}
    All structural fields are copied (tracking_link, preview_url included).
    """
    body = request.get_json() or {}
    try:
        record = structure_svc().clone(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 201


# ── Make live ──────────────────────────────────────────────────────────────────

@bp.route("/api/structures/<sid>/make-live", methods=["POST"])
@admin_required
def api_structures_make_live(sid: str):
    """
    Promote a structure to Live.  Automatically pauses the current live version.
    Valid from pending OR paused (re-activation).
    """
    try:
        record = structure_svc().make_live(sid)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record)


# ── Pause ──────────────────────────────────────────────────────────────────────

@bp.route("/api/structures/<sid>/pause", methods=["POST"])
@admin_required
def api_structures_pause(sid: str):
    """Pause a structure (live → paused or pending → paused)."""
    record = structure_svc().pause(sid)
    if record is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(record)


# ── Delete ─────────────────────────────────────────────────────────────────────

@bp.route("/api/structures/<sid>", methods=["DELETE"])
@admin_required
def api_structures_delete(sid: str):
    """
    Delete a structure.  Only pending or paused structures may be deleted.
    Live structures must be paused first.
    """
    try:
        structure_svc().delete(sid)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})
