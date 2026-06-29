"""
Admin blueprint — game-config CRUD, /api/admin/games/*, /api/management/clients.

Write/destructive endpoints are protected with @admin_required (X-Admin-Key header).
Read-only GET endpoints remain open so the dashboard UI can display data without auth.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.auth    import admin_required
from backend.routes.deps    import analytics_svc, game_config_svc, partner_svc
from backend.services.game_config import Conflict

bp = Blueprint("admin", __name__)


# ── Game config CRUD ──────────────────────────────────────────────────────────

@bp.route("/api/admin/games", methods=["GET"])
def api_admin_games_get():
    return jsonify(game_config_svc().list())


@bp.route("/api/admin/games", methods=["POST"])
@admin_required
def api_admin_games_post():
    body = request.get_json() or {}
    try:
        record = game_config_svc().create(body)
    except Conflict as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 201


@bp.route("/api/admin/games/<cid>", methods=["PUT"])
@admin_required
def api_admin_games_put(cid):
    body   = request.get_json() or {}
    result = game_config_svc().update(cid, body)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.route("/api/admin/games/<cid>", methods=["DELETE"])
@admin_required
def api_admin_games_delete(cid):
    if not game_config_svc().delete(cid):
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": "deleted"})


# ── Game discovery endpoints ──────────────────────────────────────────────────

@bp.route("/api/admin/games/status")
def api_admin_games_status():
    svc             = analytics_svc()
    gcfg_svc        = game_config_svc()
    avail_dates     = svc.get_available_dates()
    publisher_count = len(svc._publisher_svc.list())
    return jsonify(gcfg_svc.get_status(avail_dates, publisher_count=publisher_count))


@bp.route("/api/admin/games/discovered")
def api_admin_games_discovered():
    avail_dates = analytics_svc().get_available_dates()
    return jsonify(game_config_svc().get_discovered(avail_dates))


@bp.route("/api/admin/games/unconfigured")
def api_admin_games_unconfigured():
    avail_dates = analytics_svc().get_available_dates()
    return jsonify(game_config_svc().get_unconfigured(avail_dates))


# ── Management: client/partner CRUD ──────────────────────────────────────────

@bp.route("/api/management/clients", methods=["GET"])
def api_mgmt_clients_get():
    return jsonify(partner_svc().list())


@bp.route("/api/management/clients", methods=["POST"])
@admin_required
def api_mgmt_clients_post():
    body = request.get_json() or {}
    try:
        record = partner_svc().create(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 201


@bp.route("/api/management/clients/<cid>", methods=["PUT"])
@admin_required
def api_mgmt_clients_put(cid):
    body   = request.get_json() or {}
    result = partner_svc().update(cid, body)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.route("/api/management/clients/<cid>", methods=["DELETE"])
@admin_required
def api_mgmt_clients_delete(cid):
    if not partner_svc().delete(cid):
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": "deleted"})
