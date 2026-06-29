"""
backend.routes.auth — Authentication and authorization for Flask routes.

Authentication
--------------
Supabase JWT verified locally via JWKS (PyJWKClient).
Keys are fetched from {SUPABASE_URL}/auth/v1/.well-known/jwks.json once and
cached in-process — no outbound HTTP request per API call.

Authorization
-------------
app_metadata.app_role from the verified JWT payload.
Set the role in the Supabase Dashboard → Auth → Users → Edit → app_metadata:

    {"app_role": "admin"}

Supported roles
---------------
  super_admin — full system access
  admin       — administration (all existing write endpoints)
  partner     — partner portal (future)
  viewer      — read-only (future)

Public decorators
-----------------
  @login_required
      Any valid JWT — role is not checked.

  @roles_required("admin", "super_admin")
      Valid JWT whose app_role is one of the listed roles.
      Returns 401 on missing/invalid token; 403 on role mismatch.
      Raises ValueError at decoration time for unknown role names.

  @admin_required
      Alias: roles_required("admin", "super_admin").
      Used on all existing write/destructive endpoints.

  @jwt_required
      Alias: login_required.

g.current_user (set on every authenticated request)
----------------------------------------------------
  sub          str        Supabase user UUID
  email        str        user email address
  app_metadata dict       raw app_metadata block from the JWT
  app_role     str|None   shortcut: app_metadata["app_role"] if valid, else None
  (all other standard JWT claims are also present)

Dev mode: SUPABASE_URL not set → all checks bypassed, g.current_user = None.
"""
from __future__ import annotations

import functools

import jwt as _jwt
from flask import g, jsonify, request
from loguru import logger


# ── Supported roles ───────────────────────────────────────────────────────────

_VALID_ROLES = frozenset({"super_admin", "admin", "partner", "viewer"})


# ── JWKS client singleton ──────────────────────────────────────────────────────

_jwks_client = None
_init_tried  = False


def _get_jwks_client():
    """Return a lazily initialised PyJWKClient, or None on failure."""
    global _jwks_client, _init_tried
    if _init_tried:
        return _jwks_client
    _init_tried = True
    try:
        from jwt import PyJWKClient
        from backend.config import SUPABASE_URL
        if SUPABASE_URL:
            jwks_uri = f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            _jwks_client = PyJWKClient(jwks_uri, cache_keys=True, max_cached_keys=10)
            logger.info(f"JWT auth: JWKS client initialised → {jwks_uri}")
        else:
            logger.debug("SUPABASE_URL not set — JWT auth bypassed (dev mode)")
    except Exception as exc:
        logger.warning(f"JWKS client init failed — JWT auth unavailable: {exc}")
    return _jwks_client


# ── Local JWT verification ────────────────────────────────────────────────────

def _verify_jwt(token: str) -> dict:
    """
    Verify a Supabase access token entirely in-process.

    1. Resolve the signing key from the cached JWKS (re-fetches on kid miss).
    2. Verify signature, exp, iss={SUPABASE_URL}/auth/v1, aud="authenticated".
    3. Extract and validate app_metadata.app_role.
    4. Return the full payload enriched with a top-level ``app_role`` shortcut.

    Raises
    ------
    jwt.ExpiredSignatureError  — token has expired
    jwt.InvalidTokenError      — any other verification failure
    RuntimeError               — JWKS client not initialised
    """
    client = _get_jwks_client()
    if client is None:
        raise RuntimeError("JWKS client is not available")

    from backend.config import SUPABASE_URL
    expected_issuer = f"{SUPABASE_URL.rstrip('/')}/auth/v1"

    signing_key = client.get_signing_key_from_jwt(token)
    payload = _jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience="authenticated",
        issuer=expected_issuer,
        options={"require": ["exp", "sub", "iss"]},
    )

    # Enrich with a validated app_role shortcut.
    # app_role is set to None for unrecognised or absent values so that
    # role checks always produce a clean True/False comparison.
    app_metadata = payload.get("app_metadata") or {}
    raw_role     = app_metadata.get("app_role", "")
    payload["app_role"] = raw_role if raw_role in _VALID_ROLES else None

    return payload


# ── Shared authentication step ────────────────────────────────────────────────

def _authenticate() -> tuple[dict | None, tuple | None]:
    """
    Extract the Bearer token, verify it, and populate g.current_user.

    Called only when SUPABASE_URL is set (callers must check dev mode first).

    Returns
    -------
    (payload, None)         — success; g.current_user is set to payload
    (None, (resp, status))  — failure; caller must ``return`` the error tuple
    """
    if _get_jwks_client() is None:
        logger.error("auth: JWKS client unavailable — check SUPABASE_URL and network")
        return None, (jsonify({
            "error":   "Service Unavailable",
            "message": "Authentication service is not configured correctly.",
        }), 503)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, (jsonify({
            "error":   "Unauthorized",
            "message": "Authorization: Bearer <token> header is required.",
        }), 401)

    token = auth_header[7:].strip()
    if not token:
        return None, (jsonify({"error": "Unauthorized", "message": "Token is empty."}), 401)

    try:
        payload = _verify_jwt(token)
        g.current_user = payload
        return payload, None
    except _jwt.ExpiredSignatureError:
        return None, (jsonify({
            "error":   "Unauthorized",
            "message": "Token has expired. Please log in again.",
        }), 401)
    except _jwt.InvalidTokenError as exc:
        logger.debug(f"JWT verification failed: {exc}")
        return None, (jsonify({
            "error":   "Unauthorized",
            "message": "Invalid token. Please log in again.",
        }), 401)
    except Exception as exc:
        logger.warning(f"JWT verification error: {exc}")
        return None, (jsonify({
            "error":   "Unauthorized",
            "message": "Could not verify token.",
        }), 401)


# ── Public decorators ─────────────────────────────────────────────────────────

def login_required(fn):
    """
    Require a valid Supabase JWT. Role is not checked — any authenticated
    user may access the decorated route.

    Sets g.current_user to the decoded payload (including ``app_role``).
    Dev mode (SUPABASE_URL unset): g.current_user = None, handler called.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from backend.config import SUPABASE_URL
        if not SUPABASE_URL:
            g.current_user = None
            return fn(*args, **kwargs)
        _, err = _authenticate()
        if err is not None:
            return err
        return fn(*args, **kwargs)
    return wrapper


def roles_required(*allowed_roles: str):
    """
    Decorator factory: require a valid JWT whose ``app_role`` is one of
    ``allowed_roles``.

    Usage::

        @roles_required("admin", "super_admin")
        def create_game_config(): ...

        @roles_required("partner")
        def partner_dashboard(): ...

    Returns 401 if the token is missing or invalid.
    Returns 403 if the token is valid but ``app_role`` is not in allowed_roles
    (including the case where no role has been assigned to the user).

    Raises ValueError at decoration time if any role name is not in
    _VALID_ROLES — this surfaces typos immediately on app startup.

    Dev mode (SUPABASE_URL unset): g.current_user = None, handler called.
    """
    unknown = frozenset(allowed_roles) - _VALID_ROLES
    if unknown:
        raise ValueError(
            f"roles_required: unknown role(s) {sorted(unknown)!r}. "
            f"Valid roles are: {sorted(_VALID_ROLES)!r}"
        )

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from backend.config import SUPABASE_URL
            if not SUPABASE_URL:
                g.current_user = None
                return fn(*args, **kwargs)

            payload, err = _authenticate()
            if err is not None:
                return err

            app_role = payload.get("app_role")   # None if not set or unrecognised
            if app_role not in allowed_roles:
                logger.debug(
                    f"roles_required: access denied — "
                    f"sub={payload.get('sub')!r} "
                    f"app_role={app_role!r} "
                    f"required={sorted(allowed_roles)!r}"
                )
                return jsonify({
                    "error":   "Forbidden",
                    "message": "You do not have permission to perform this action.",
                }), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Convenience aliases ───────────────────────────────────────────────────────

# Evaluated at import time: roles_required("admin", "super_admin") returns the
# `decorator` function.  @admin_required on any route fn calls decorator(fn),
# exactly as before — no blueprint changes required.
admin_required = roles_required("admin", "super_admin")

# @jwt_required is a semantic alias for @login_required
jwt_required = login_required
