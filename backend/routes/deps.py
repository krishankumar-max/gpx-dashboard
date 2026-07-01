"""
backend.routes.deps — Service accessors for Blueprint route handlers.

Services are attached to the Flask app object by app.py, and accessed
here via current_app so blueprints don't need direct imports from app.
"""
from __future__ import annotations

from flask import current_app


def analytics_svc():
    return current_app.analytics_svc  # type: ignore[attr-defined]


def game_config_svc():
    return current_app.game_config_svc  # type: ignore[attr-defined]


def publisher_svc():
    return current_app.publisher_svc  # type: ignore[attr-defined]


def partner_svc():
    return current_app.partner_svc  # type: ignore[attr-defined]


def funnel_svc():
    return current_app.funnel_svc  # type: ignore[attr-defined]


def sync_svc():
    return current_app.sync_svc  # type: ignore[attr-defined]


def sync_engine():
    """Return the _do_sync callable (kept in app.py, stored on Flask app)."""
    return current_app.sync_engine  # type: ignore[attr-defined]


def structure_svc():
    return current_app.structure_svc  # type: ignore[attr-defined]
