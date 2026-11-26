"""Stateless Supabase Auth REST adapter: no shared cookies or auth sessions.

Ported from feat/backend-auth (backend/supabase_auth.py) onto the app/
layout. Logic unchanged — this is the deliberate design: BE verifies every
session by calling Supabase's /auth/v1/user remotely rather than decoding
the access token locally."""
import httpx
from fastapi import Request
from pydantic import ValidationError

from app.schemas.auth import User


class AuthError(Exception):
    def __init__(
        self, status: int, message: str, clear_cookies: bool = False, *,
        provider_status: int | None = None, provider_code: str | None = None,
    ):
        self.status = status
        self.message = message
        self.clear_cookies = clear_cookies
        self.provider_status = provider_status
        self.provider_code = provider_code


def _error_body(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _email_error_code(response: httpx.Response) -> str | None:
    data = _error_body(response)
    code = data.get("error_code")
    if code in ("user_already_exists", "email_exists", "over_email_send_rate_limit", "over_request_rate_limit"):
        return code
    # Older GoTrue releases returned the exact duplicate message without a code.
    if code is None and data.get("msg") == "User already registered":
        return "user_already_exists"
    return None


_DEFINITIVE_REFRESH_ERRORS = (
    "refresh_token_not_found", "refresh_token_already_used",
    "session_expired", "session_not_found", "user_not_found", "user_banned",
)


async def supabase_request(
    request: Request,
    method: str,
    path: str,
    *,
    body=None,
    token: str | None = None,
    params=None,
    invalid_status=401,
):
    settings = request.app.state.auth_settings
    if not settings.supabase_url or not settings.publishable_key:
        raise AuthError(503, "Authentication service is not configured")
    headers = {"apikey": settings.publishable_key}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # A new client for each call prevents cross-user headers/cookie/session leakage.
    transport = getattr(request.app.state, "supabase_transport", None)
    try:
        async with httpx.AsyncClient(
            timeout=10, transport=transport, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method, settings.supabase_url + "/auth/v1" + path, headers=headers, json=body, params=params
            )
    except httpx.RequestError:
        raise AuthError(503, "Authentication service is unavailable") from None
    status = response.status_code
    code = _email_error_code(response) if path in {"/signup", "/resend"} and 400 <= status < 500 else None
    if path == "/recover" and status == 429 and _error_body(response).get("error_code") == "over_request_rate_limit":
        code = "over_request_rate_limit"
    if path == "/token" and (params or {}).get("grant_type") == "pkce" and 400 <= status < 500:
        if _error_body(response).get("error_code") in ("flow_state_expired", "otp_expired"):
            raise AuthError(410, "The email link expired")
    if status == 429:
        raise AuthError(429, "Too many authentication attempts; try again later",
                        provider_status=status, provider_code=code)
    if status >= 500:
        raise AuthError(503, "Authentication service is unavailable", provider_status=status)
    if 400 <= status < 500 and path == "/token" and (params or {}).get("grant_type") == "refresh_token":
        if _error_body(response).get("error_code") in _DEFINITIVE_REFRESH_ERRORS:
            raise AuthError(401, "Invalid or expired session")
        raise AuthError(503, "Unable to verify the session. Try again later.")
    if status in {400, 401, 403, 422}:
        # Never expose upstream bodies or distinguish whether an account exists.
        raise AuthError(invalid_status, "Authentication request was rejected",
                        provider_status=status, provider_code=code)
    if not 200 <= status < 300:
        raise AuthError(503, "Unexpected authentication service response")
    if status == 204:
        return {}
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise AuthError(503, "Invalid authentication service response") from None


def verified_user(data):
    try:
        return User.model_validate(data)
    except (ValidationError, TypeError):
        raise AuthError(503, "Invalid authentication service response") from None
