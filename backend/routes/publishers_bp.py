"""
Publishers blueprint — /api/publishers/*, /api/management/publishers.

Management write endpoints are protected with @admin_required (Supabase JWT, role: admin or super_admin).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.auth    import admin_required
from backend.routes.deps    import analytics_svc, publisher_svc
from backend.routes.helpers import read_filters, resolve_range

bp = Blueprint("publishers", __name__)


# ── Analytics: publisher pages ─────────────────────────────────────────────────

@bp.route("/api/publishers/kpis")
def api_publishers_kpis():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    configured = publisher_svc().list()
    return jsonify(analytics_svc().publishers_kpis(fd, td, partners, offers, goals, configured))


@bp.route("/api/publishers/detail")
def api_publishers_detail():
    fd, td, _, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    partner = request.args.get("partner", "").strip()
    if not partner:
        return jsonify({"error": "partner is required"}), 400
    return jsonify(analytics_svc().publishers_detail(partner, fd, td, offers, goals))


@bp.route("/api/publishers/profile")
def api_publishers_profile():
    fd, td, _, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    partner = request.args.get("partner", "").strip()
    if not partner:
        return jsonify({"error": "partner is required"}), 400
    return jsonify(analytics_svc().publishers_profile(partner, fd, td, offers, goals))


@bp.route("/api/publishers/offer-detail")
def api_pub_offer_detail():
    fd, td, _, _, goals = read_filters()
    fd, td = resolve_range(fd, td)
    partner = request.args.get("partner", "").strip()
    offer   = request.args.get("offer",   "").strip()
    if not partner or not offer:
        return jsonify({"error": "partner and offer are required"}), 400
    return jsonify(analytics_svc().pub_offer_detail(partner, offer, fd, td, goals))


@bp.route("/api/publishers/summary")
def api_publishers_summary():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().publishers_summary(fd, td, partners, offers, goals))


@bp.route("/api/publishers/comparison")
def api_publishers_comparison():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    if not offers:
        return jsonify({"error": "at least one offer is required"}), 400
    return jsonify(analytics_svc().publishers_comparison(fd, td, partners, offers, goals))


@bp.route("/api/publishers/map")
def api_publishers_map():
    return jsonify(publisher_svc().get_map())


# ── Management: publisher CRUD ─────────────────────────────────────────────────

@bp.route("/api/management/publishers", methods=["GET"])
def api_mgmt_publishers_get():
    return jsonify(publisher_svc().list())


@bp.route("/api/management/publishers", methods=["POST"])
@admin_required
def api_mgmt_publishers_post():
    body = request.get_json() or {}
    try:
        record = publisher_svc().create(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(record), 201


@bp.route("/api/management/publishers/<pid>", methods=["PUT"])
@admin_required
def api_mgmt_publishers_put(pid):
    body   = request.get_json() or {}
    result = publisher_svc().update(pid, body)
    if result is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.route("/api/management/publishers/<pid>", methods=["DELETE"])
@admin_required
def api_mgmt_publishers_delete(pid):
    if not publisher_svc().delete(pid):
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": "deleted"})
