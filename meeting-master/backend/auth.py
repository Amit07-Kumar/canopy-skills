"""
Meeting Master Auth — Descope integration via lehana_auth library.

Uses the centralized auth-service at auth.lehana.in to validate Descope
JWTs and resolve per-app tier. Guest tokens are handled separately using
local JWT decode (python-jose) for backward compatibility.

Two auth patterns are provided:
1. @require_auth decorator — for routes that ONLY accept Descope tokens
2. get_current_user() dependency — for routes that accept BOTH Descope AND guest tokens

Pattern reference: /root/ideas/bio-bandish/backend/auth.py
Library source: /root/repo/lehana-auth/lehana_auth/auth.py
"""

# Use relative/fallback import for config to match api.py pattern
try:
    from . import config
except ImportError:
    import config

import os
import logging
from typing import Optional
from fastapi import Request, HTTPException, Header
from jose import JWTError, jwt as jose_jwt

try:
    from lehana_auth import (
        LehanaAuthConfig,
        require_auth as la_require_auth,
        require_tier as la_require_tier,
        require_admin as la_require_admin,
    )
    _USING_LOCAL_AUTH_COMPAT = False
except ImportError:
    try:
        from .lehana_auth_compat import (
            LehanaAuthConfig,
            require_auth as la_require_auth,
            require_tier as la_require_tier,
            require_admin as la_require_admin,
        )
    except ImportError:
        from lehana_auth_compat import (
            LehanaAuthConfig,
            require_auth as la_require_auth,
            require_tier as la_require_tier,
            require_admin as la_require_admin,
        )
    _USING_LOCAL_AUTH_COMPAT = True

logger = logging.getLogger(__name__)
if _USING_LOCAL_AUTH_COMPAT:
    logger.warning("lehana_auth is not installed; using the local auth compatibility layer.")

# ── Auth Configuration ────────────────────────────────────────────────────────
auth_config = LehanaAuthConfig(
    app_name=config.APP_NAME_IN_AUTH,
    auth_service_url=config.AUTH_SERVICE_URL,
)

# ── Descope-Only Decorator ────────────────────────────────────────────────────
# Use on endpoints that require a real Descope account (no guests allowed).
# After success, request.state.user has: id, email, name, tier, raw.
require_descope_auth = la_require_auth(auth_config)


def require_tier(min_tier: str):
    """Require a minimum tier level (e.g. 'PAID', 'PREMIUM', 'ADMIN').
    Must be stacked after @require_descope_auth.
    """
    return la_require_tier(auth_config, min_tier)


def require_admin(func=None):
    """Require ADMIN tier. Combines require_auth + admin tier check."""
    tier_guard = la_require_admin(auth_config)

    def decorator(target_func):
        return require_descope_auth(tier_guard(target_func))

    if func is None:
        return decorator
    return decorator(func)


# ── Guest Token Validation ────────────────────────────────────────────────────
def _decode_local_token(token: str) -> Optional[dict]:
    """Decode a locally-issued JWT (guest OR Descope-exchanged).

    Returns user dict or None.  Works for both:
    - Guest tokens (is_guest=True, issued by /auth/guest)
    - Descope-exchanged tokens (provider='descope', issued by /auth/descope-login)
    """
    try:
        secret = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET", config.JWT_SECRET_KEY)
        if not secret:
            return None
        payload = jose_jwt.decode(token, secret, algorithms=[config.JWT_ALGORITHM])
        is_guest = payload.get("is_guest", False)
        provider = payload.get("provider", "")
        # Accept guest tokens and descope-exchanged tokens
        if not is_guest and provider != "descope":
            return None
        return {
            "id": payload.get("sub", ""),
            "email": payload.get("email", ""),
            "name": payload.get("name", "Guest" if is_guest else "User"),
            "tier": payload.get("tier", "FREE"),
            "is_guest": is_guest,
            "raw": payload,
        }
    except (JWTError, ValueError, Exception):
        return None


# ── Combined Auth (Descope + Guest) ──────────────────────────────────────────
# FastAPI Depends()-compatible function that tries Descope first, then guest JWT.
# This replaces the old get_current_user() + require_auth() pattern.

import httpx

_http_client = httpx.AsyncClient(timeout=10.0)


async def get_current_user(authorization: str = Header(None)) -> Optional[dict]:
    """Extract user from local JWT (guest/descope-exchanged) or raw Descope JWT.

    Priority:
    1. Local JWT decode (fast, no network — handles guest + descope-exchanged tokens)
    2. Auth-service /v1/validate (for raw Descope JWTs not yet exchanged)
    """
    if not authorization:
        return None

    try:
        scheme, token = authorization.split(None, 1)
        if scheme.lower() != "bearer":
            return None
    except ValueError:
        return None

    # 1. Try local JWT first (covers both guest and descope-exchanged tokens)
    #    This is fast (no network call) and handles the common case after login.
    local_user = _decode_local_token(token)
    if local_user:
        local_user["user_id"] = local_user["id"]  # backward compat alias
        return local_user

    # 2. Fallback: try raw Descope JWT via auth-service /v1/validate
    #    This handles the edge case where frontend sends a raw Descope sessionJwt
    #    (e.g., before the descope-login exchange completes).
    try:
        resp = await _http_client.post(
            f"{config.AUTH_SERVICE_URL}/v1/validate",
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
            },
        )
        if resp.status_code == 200:
            auth_data = resp.json()
            user = auth_data.get("user", {})
            apps = (user.get("customAttributes") or {}).get("apps", {})
            app_cfg = apps.get(config.APP_NAME_IN_AUTH, {})
            tier = str(app_cfg.get("tier", "free")).upper() if isinstance(app_cfg, dict) else "FREE"
            return {
                "id": user.get("userId", ""),
                "user_id": user.get("userId", ""),
                "email": auth_data.get("loginId", user.get("email", "")),
                "name": user.get("name", ""),
                "tier": tier,
                "is_guest": False,
                "raw": auth_data,
            }
    except Exception as e:
        logger.debug(f"Auth-service validate failed: {e}")

    return None


async def require_auth(authorization: str = Header(None)) -> dict:
    """FastAPI Depends() that requires authentication (Descope or guest).
    Returns user dict or raises 401.
    """
    # Check auth bypass flag
    if config.AUTH_DISABLED:
        return {
            "id": "auth_disabled",
            "user_id": "auth_disabled",
            "email": "",
            "name": "Auth Disabled",
            "tier": "ADMIN",
            "is_guest": False,
            "raw": {},
        }

    user = await get_current_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ── Helper Functions ──────────────────────────────────────────────────────────
def get_user_tier(request: Request) -> str:
    """Get the effective tier of the current user from request.state."""
    return getattr(request.state, "user", {}).get("tier", "FREE")


def get_user_id(request: Request) -> str:
    """Get the Descope user ID (or guest ID) from request.state."""
    return getattr(request.state, "user", {}).get("id", "")
