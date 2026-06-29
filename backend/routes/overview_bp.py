"""
Overview blueprint — /api/overview/*, /api/alerts, /api/funnel/data.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.deps    import analytics_svc
from backend.routes.helpers import read_filters, resolve_range

bp = Blueprint("overview", __name__)


@bp.route("/api/overview/kpis")
def api_overview_kpis():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().overview_kpis(fd, td, partners, offers, goals))


@bp.route("/api/overview/comparisons")
def api_overview_comparisons():
    _, _, partners, offers, goals = read_filters()
    return jsonify(analytics_svc().overview_comparisons(partners, offers, goals))


@bp.route("/api/overview/trend")
def api_overview_trend():
    fd, td, partners, offers, goals = read_filters()
    try:
        days = int(request.args.get("days", 0))
    except ValueError:
        days = 0
    return jsonify(analytics_svc().overview_trend(fd, td, days, partners, offers, goals))


@bp.route("/api/overview/leaderboards")
def api_overview_leaderboards():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().overview_leaderboards(fd, td, partners, offers, goals))


@bp.route("/api/overview/alerts")
def api_overview_alerts():
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().overview_alerts(fd, td, partners, offers, goals))


@bp.route("/api/alerts")
def api_alerts():
    """Global alert centre — same data as overview/alerts."""
    fd, td, partners, offers, goals = read_filters()
    fd, td = resolve_range(fd, td)
    return jsonify(analytics_svc().overview_alerts(fd, td, partners, offers, goals))


@bp.route("/api/funnel/data")
def api_funnel_data():
    fd, td, partners, offers, _ = read_filters()
    if fd is None and td is None:
        from backend.routes.helpers import default_range
        fd, td = default_range()
    return jsonify(analytics_svc().funnel_data(offers, fd, td, partners))
