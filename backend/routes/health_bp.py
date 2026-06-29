"""
Health blueprint — /api/health/digest, /api/operations/recommendations.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from backend.routes.deps    import analytics_svc
from backend.routes.helpers import read_filters, resolve_range

bp = Blueprint("health", __name__)


@bp.route("/api/health/digest")
def api_health_digest():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().health_digest(fd, td, partners, offers, goals))


@bp.route("/api/operations/recommendations")
def api_operations_recommendations():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().operations_recommendations(fd, td, partners, offers, goals))
