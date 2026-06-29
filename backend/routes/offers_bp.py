"""
Offers blueprint — /api/offers/*.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.deps    import analytics_svc
from backend.routes.helpers import read_filters, resolve_range

bp = Blueprint("offers", __name__)


@bp.route("/api/offers/profile")
def api_offers_profile():
    fd, td, partners, _, goals = read_filters()
    fd, td = resolve_range(fd, td)
    offer = request.args.get("offer", "").strip()
    if not offer:
        return jsonify({"error": "offer is required"}), 400
    return jsonify(analytics_svc().offers_profile(offer, fd, td, partners, goals))


@bp.route("/api/offers/summary")
def api_offers_summary():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().offers_summary(fd, td, partners, offers, goals))


@bp.route("/api/offers/publishers")
def api_offers_publishers():
    fd, td, partners, _, goals = read_filters()
    fd, td = resolve_range(fd, td)
    offer = request.args.get("offer", "").strip()
    if not offer:
        return jsonify({"error": "offer is required"}), 400
    return jsonify(analytics_svc().offers_publishers(offer, fd, td, partners, goals))


@bp.route("/api/offers/map")
def api_offers_map():
    svc         = analytics_svc()
    avail_dates = svc.get_available_dates()
    return jsonify(svc.offers_map(avail_dates))
