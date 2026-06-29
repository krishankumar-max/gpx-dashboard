"""
Analytics blueprint — /api/analytics/*.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.deps    import analytics_svc
from backend.routes.helpers import read_filters, resolve_range

bp = Blueprint("analytics", __name__)


@bp.route("/api/analytics/weekly")
def api_analytics_weekly():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().analytics_weekly(fd, td, partners, offers, goals))


@bp.route("/api/analytics/monthly")
def api_analytics_monthly():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().analytics_monthly(fd, td, partners, offers, goals))


@bp.route("/api/analytics/drivers")
def api_analytics_drivers():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().analytics_drivers(fd, td, partners, offers, goals))
