"""
Small compatibility layer for environments where `lehana_auth` is unavailable.

This keeps local Docker and repo-based development working while preserving
the same public API used by backend/auth.py.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Optional

import httpx
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_TIER_ORDER = {
    "FREE": 0,
    "PAID": 1,
    "PREMIUM": 2,
    "ADMIN": 3,
}


@dataclass(frozen=True)
class LehanaAuthConfig:
    app_name: str
    auth_service_url: str


_http_client = httpx.AsyncClient(timeout=10.0)


def _extract_request(args, kwargs) -> Request:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request

    for arg in args:
        if isinstance(arg, Request):
            return arg

    raise RuntimeError(
        "A FastAPI Request parameter is required when using the local auth compatibility layer."
    )


def _normalize_apps(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except (TypeError, ValueError):
            return {}
    return {}


async def _validate_request(auth_config: LehanaAuthConfig, request: Request) -> dict:
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        resp = await _http_client.post(
            f"{auth_config.auth_service_url}/v1/validate",
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
            },
        )
    except httpx.RequestError as exc:
        logger.debug("Auth-service validate failed: %s", exc)
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Not authenticated")

    auth_data = resp.json()
    user = auth_data.get("user", {})
    apps = _normalize_apps((user.get("customAttributes") or {}).get("apps", {}))
    app_cfg = apps.get(auth_config.app_name, {}) if isinstance(apps, dict) else {}
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


async def _call_with_user(func, request: Request, user: dict, args, kwargs):
    request.state.user = user
    result = func(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def require_auth(auth_config: LehanaAuthConfig):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            user = await _validate_request(auth_config, request)
            return await _call_with_user(func, request, user, args, kwargs)

        return wrapper

    return decorator


def require_tier(auth_config: LehanaAuthConfig, min_tier: str):
    minimum = _TIER_ORDER.get(min_tier.upper(), _TIER_ORDER["FREE"])

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _extract_request(args, kwargs)
            user = getattr(request.state, "user", None) or await _validate_request(auth_config, request)
            current = _TIER_ORDER.get(str(user.get("tier", "FREE")).upper(), _TIER_ORDER["FREE"])
            if current < minimum:
                raise HTTPException(status_code=403, detail="Insufficient tier")
            return await _call_with_user(func, request, user, args, kwargs)

        return wrapper

    return decorator


def require_admin(auth_config: LehanaAuthConfig):
    return require_tier(auth_config, "ADMIN")
