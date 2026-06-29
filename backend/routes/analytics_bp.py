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
    _, _, partners, offers, goals = read_filters()
    # analytics_weekly uses its own 8-week rolling window internally; fd/td unused
    return jsonify(analytics_svc().analytics_weekly(partners, offers, goals))


@bp.route("/api/analytics/monthly")
def api_analytics_monthly():
    _, _, partners, offers, goals = read_filters()
    # analytics_monthly uses its own 6-month rolling window internally; fd/td unused
    return jsonify(analytics_svc().analytics_monthly(partners, offers, goals))


@bp.route("/api/analytics/drivers")
def api_analytics_drivers():
    _, _, partners, offers, goals = read_filters()
    # analytics_drivers uses its own current/previous 7-day windows; fd/td unused
    return jsonify(analytics_svc().analytics_drivers(partners, offers, goals))
