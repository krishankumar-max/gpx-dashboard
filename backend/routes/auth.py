"""
backend.routes.auth — Session-based authentication.

Single administrator account loaded from environment variables:

    LOGIN_EMAIL         — admin email address
    LOGIN_PASSWORD_HASH — bcrypt hash of the password

Generate a hash:
    python3 -c "import bcrypt; print(bcrypt.hashpw(b'<password>', bcrypt.gensalt(12)).decode())"

Routes (blueprint: auth_bp)
----------------------------
  POST /login   — verify credentials, set Flask session, return {"ok": true, "email": "..."}
  POST /logout  — clear session, return {"ok": true}
  GET  /me      — return {"authenticated": bool, "email": "..."}; 401 if not logged in

Public decorators
-----------------
  @login_required
      Require an active Flask session.  Returns 401 if not authenticated.

  @roles_required(*roles)
      Backward-compatible factory decorator.  With a single local admin, all
      authenticated sessions have full access.  Kept so existing blueprints
      using @admin_required continue to work without modification.

  @admin_required
      Alias for login_required.

  @jwt_required
      Alias for login_required (backward compatibility).
"""
from __future__ import annotations

import functools

import bcrypt
from flask import Blueprint, jsonify, request, session
from loguru import logger

from backend.config import LOGIN_EMAIL, LOGIN_PASSWORD_HASH

bp = Blueprint("auth", __name__)


# ── Internal helper ───────────────────────────────────────────────────────────

def _is_authenticated() -> bool:
    return bool(session.get("authenticated"))


# ── Auth routes ───────────────────────────────────────────────────────────────

@bp.route("/login", methods=["POST"])
def login():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    # Both checks must pass; evaluate both before branching to resist timing attacks.
    email_ok    = (email == LOGIN_EMAIL.strip().lower())
    password_ok = (
        bool(LOGIN_PASSWORD_HASH)
        and bcrypt.checkpw(password.encode("utf-8"), LOGIN_PASSWORD_HASH.encode("utf-8"))
    )

    if not (email_ok and password_ok):
        logger.warning(f"auth: login failed for {email!r}")
        return jsonify({"error": "Invalid email or password."}), 401

    session.clear()
    session["authenticated"] = True
    session["email"]          = LOGIN_EMAIL
    session.permanent         = True
    logger.info(f"auth: login successful for {email!r}")
    return jsonify({"ok": True, "email": LOGIN_EMAIL})


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/me")
def me():
    if not _is_authenticated():
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "email": session.get("email", "")})


# ── Public decorators ─────────────────────────────────────────────────────────

def login_required(fn):
    """Require an active Flask session cookie."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_authenticated():
            return jsonify({"error": "Unauthorized", "message": "Login required."}), 401
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*_roles: str):
    """
    Backward-compatible decorator factory.
    With a single local admin account all authenticated sessions have full
    access, so the role list is accepted but ignored.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not _is_authenticated():
                return jsonify({"error": "Unauthorized", "message": "Login required."}), 401
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Convenience aliases ───────────────────────────────────────────────────────

# admin_required is used on all write/destructive endpoints in admin_bp,
# publishers_bp, etc.  It must be a plain decorator (not a factory result) so
# that @admin_required works without parentheses.  login_required satisfies
# this because every authenticated session is the admin.
admin_required = login_required

# jwt_required kept for any future code that references it.
jwt_required = login_required
