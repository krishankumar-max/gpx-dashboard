"""
backend.routes.helpers — Request-parsing utilities shared by all blueprints.

These are pure HTTP/Flask concerns: reading query-string params, parsing
dates, splitting comma-separated lists.  No business logic lives here.
"""
from __future__ import annotations

import datetime as dt

from flask import request

from backend.utils import ist_today


def parse_csv(value: str | None) -> list[str]:
    """Split a comma-separated query-string value into a clean list."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def default_range() -> tuple[dt.date, dt.date]:
    today = ist_today()
    return today - dt.timedelta(days=6), today


def read_filters() -> tuple[
    dt.date | None, dt.date | None, list[str], list[str], list[str]
]:
    """Parse the five standard filter params from the current request."""
    return (
        parse_date(request.args.get("from_date")),
        parse_date(request.args.get("to_date")),
        parse_csv(request.args.get("partners")),
        parse_csv(request.args.get("offers")),
        parse_csv(request.args.get("goals")),
    )


def resolve_range(
    from_date: dt.date | None,
    to_date:   dt.date | None,
) -> tuple[dt.date, dt.date]:
    """Fill None dates with the default 7-day window."""
    fd, td = default_range()
    return (from_date or fd), (to_date or td)
