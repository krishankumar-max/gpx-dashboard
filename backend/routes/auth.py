"""
backend.routes.auth — Admin API key authentication.

Endpoints decorated with @admin_required require the caller to supply
an X-Admin-Key header whose value matches the ADMIN_KEY environment variable.

If ADMIN_KEY is empty (the default for local development), the check is
skipped entirely so the dashboard works out of the box without configuration.

In production, set ADMIN_KEY to a long random string (openssl rand -hex 32).
The same value must be included in every write/destructive API call:

    curl -X POST http://your-server/api/admin/games \\
         -H "X-Admin-Key: <your-key>" \\
         -H "Content-Type: application/json" \\
         -d '{"offer_id": "...", ...}'
"""
from __future__ import annotations

import functools

from flask import jsonify, request

from backend.config import ADMIN_KEY


def admin_required(fn):
    """
    Decorator that enforces X-Admin-Key header authentication.

    When ADMIN_KEY is set: return 401 if the header is missing or wrong.
    When ADMIN_KEY is empty: pass through (development mode).
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if ADMIN_KEY:
            provided = request.headers.get("X-Admin-Key", "")
            if provided != ADMIN_KEY:
                return jsonify({
                    "error": "Unauthorized",
                    "message": "X-Admin-Key header is required for this endpoint.",
                }), 401
        return fn(*args, **kwargs)
    return wrapper
