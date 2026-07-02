"""
Manual Overrides blueprint.

Endpoints
---------
GET    /api/admin/overrides             — list all overrides
POST   /api/admin/overrides             — create or update (upsert by date+pub+offer)
DELETE /api/admin/overrides/<oid>       — delete a specific override
GET    /api/admin/overrides/options     — publisher + offer lists for dropdowns

Auth: all write endpoints require @admin_required.  GET endpoints are open.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.auth import admin_required
from backend.routes.deps import override_svc, publisher_svc, game_config_svc

bp = Blueprint("overrides", __name__)


# ── List all ──────────────────────────────────────────────────────────────────

@bp.route("/api/admin/overrides")
def api_overrides_list():
    """Return all manual overrides, newest first."""
    svc = override_svc()
    if svc is None:
        return jsonify([])
    return jsonify(svc.list())


# ── Options (publishers + offers for dropdowns) ───────────────────────────────

@bp.route("/api/admin/overrides/options")
def api_overrides_options():
    """
    Return {publishers, offers} lists for the Add Override form dropdowns.

    publishers: [{publisher_id, partner_name}]
    offers:     [{offer_id, offer_name}]
    """
    pubs = publisher_svc().list()
    publishers = [
        {"publisher_id": str(p.get("publisher_id", "")), "partner_name": p.get("partner_name", "")}
        for p in pubs
        if p.get("publisher_id") and p.get("enabled", True)
    ]
    publishers.sort(key=lambda p: p["partner_name"].lower())

    gc_svc = game_config_svc()
    configs = gc_svc.list()
    offers = [
        {"offer_id": str(c.get("offer_id", "")), "offer_name": c.get("offer_name", "")}
        for c in configs
        if c.get("offer_id")
    ]
    offers.sort(key=lambda o: o["offer_name"].lower())

    return jsonify({"publishers": publishers, "offers": offers})


# ── Upsert (create or update) ─────────────────────────────────────────────────

@bp.route("/api/admin/overrides", methods=["POST"])
@admin_required
def api_overrides_upsert():
    """
    Create or update a manual override.

    Body (JSON):
        date              required   YYYY-MM-DD
        publisher_id      required
        offer_id          required
        publisher_name    optional
        offer_name        optional
        revenue_override  optional   float or null (null = no override)
        cost_override     optional   float or null
        reason            optional
        notes             optional
        created_by        optional   (defaults to JWT sub if available)
    """
    body = request.get_json() or {}

    # Inject created_by from JWT if not supplied
    if not body.get("created_by"):
        from flask import g
        body["created_by"] = getattr(g, "user_email", None)

    svc = override_svc()
    if svc is None:
        return jsonify({"error": "Override service not configured"}), 503

    try:
        record = svc.upsert(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 200


# ── Delete ────────────────────────────────────────────────────────────────────

@bp.route("/api/admin/overrides/<oid>", methods=["DELETE"])
@admin_required
def api_overrides_delete(oid: str):
    """Delete a manual override by id."""
    svc = override_svc()
    if svc is None:
        return jsonify({"error": "Override service not configured"}), 503

    try:
        svc.delete(oid)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True})
