"""
Shared utilities — pure functions with no Flask or service dependencies.
"""
from __future__ import annotations

import datetime as dt

_IST_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))


def ist_today() -> dt.date:
    """Return the current calendar date in Asia/Kolkata (IST)."""
    return dt.datetime.now(_IST_TZ).date()


def ist_now() -> dt.datetime:
    """Return the current datetime in IST."""
    return dt.datetime.now(_IST_TZ)
