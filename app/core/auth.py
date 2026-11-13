"""Cookie-session authentication, backend-owned.

BE owns the full login/session lifecycle — the frontend never sees Supabase
credentials or holds a bearer token; it only has httpOnly cookies BE sets.
Ported from feat/backend-auth (backend/auth.py), replacing the bearer-token
TokenVerifier seam B0 built. The verification MECHANISM carries over
unchanged, by decision: every session is verified by calling Supabase's
/auth/v1/user remotely; BE never decodes the access token locally. There is
also no dev bypass — unlike B0's DevTokenVerifier, there is nothing to leave
on by accident, because there is no bypass at all. Local dev needs a real
Supabase login.

CSRF is folded directly into current_user rather than kept as a separate
feature_user wrapper (feat/backend-auth's pattern): every protected route in
main.py already depends on current_user via app.core.deps, so adding CSRF
only to the /auth/* routes would leave every other mutating route open to
it the moment cookies replaced the Authorization header — browsers attach
cookies automatically; they never attach a bearer token on their own.

feature_security.py / FEATURE_SECURITY was not ported: its only callers on
feat/backend-auth were the pre-B2 echo-placeholder routes B2 already
replaced with the real, schema-typed API surface.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.core import auth_pkce as pkce
from app.core.auth_config import AuthSettings
from app.core.supabase_auth import AuthError, supabase_request, verified_user
from app.schemas.auth import User


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str  # the Supabase user id
    email: str


def clear_session(response: Response, settings: AuthSettings) -> None:
    for name in (settings.access_cookie, settings.refresh_cookie, pkce.recovery_name(settings)):
        response.delete_cookie(
            name, path="/", secure=settings.secure, httponly=True, samesite=settings.same_site
        )


class UpstreamSession(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr
    expires_in: int = Field(gt=0, le=60 * 60 * 24 * 7)
    user: User


def set_session(response: Response, data: dict, settings: AuthSettings) -> User:
    try:
        session = UpstreamSession.model_validate(data)
        if not session.access_token.get_secret_value() or not session.refresh_token.get_secret_value():
            raise ValueError()
    except (ValidationError, ValueError):
        raise AuthError(503, "Invalid authentication service response") from None
    for name, value, age in (
        (settings.access_cookie, session.access_token.get_secret_value(), session.expires_in),
        (settings.refresh_cookie, session.refresh_token.get_secret_value(), settings.refresh_max_age),
    ):
        response.set_cookie(
            name, value, max_age=age, expires=datetime.now(timezone.utc) + timedelta(seconds=age),
            path="/", secure=settings.secure, httponly=True, samesite=settings.same_site,
        )
    pkce.delete_cookie(response, settings, pkce.recovery_name(settings))
    return session.user


async def csrf_guard(
    request: Request,
    x_csrf_protection: Annotated[
        str | None, Header(description="Required value: 1. Also send an allowed Origin and application/json.")
    ] = None,
) -> None:
    # Exact Origin + a non-simple custom header is an explicit CSRF protocol,
    # including before login. CORS alone is not the security boundary.
    settings = request.app.state.auth_settings
    if (
        request.headers.get("origin") not in settings.trusted_origins
        or x_csrf_protection != "1"
        or (request.headers.get("sec-fetch-site") == "cross-site" and settings.same_site != "none")
    ):
        raise AuthError(403, "Origin or CSRF check failed")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise AuthError(415, "Use application/json")


def email_destination(request: Request, kind: str) -> str:
    settings = request.app.state.auth_settings
    origin = settings.email_frontend_origin
    if not origin and len(settings.frontend_origins) == 1:
        origin = settings.frontend_origins[0]
    if not origin:
        raise AuthError(503, "Email authentication destination is not configured")
    return origin + ("/login" if kind == "email" else "/reset-password")


async def _verify_session(request: Request) -> User:
    settings = request.app.state.auth_settings
    token = request.cookies.get(settings.access_cookie)
    if not token:
        raise AuthError(401, "Authentication required")
    # Supabase checks authenticity; we never decode an unverified JWT.
    try:
        data = await supabase_request(request, "GET", "/user", token=token)
    except AuthError as exc:
        if exc.status == 401:
            exc.message = "Invalid or expired session"
        raise
    user = verified_user(data)
    request.state.authenticated = True
    return user


async def current_auth_user(request: Request) -> User:
    """Raw Supabase-shaped identity, for the /auth/* routes' own response
    bodies. Every other route depends on current_user instead."""
    return await _verify_session(request)


async def current_user(
    request: Request,
    x_csrf_protection: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Every protected route in main.py depends on this (directly, or via
    app.core.deps's ProjectAccess/ProjectManage). Verifies the session, then
    — for anything but a safe method — the same CSRF check the /auth/*
    routes require."""
    user = await _verify_session(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        await csrf_guard(request, x_csrf_protection=x_csrf_protection)
    return AuthenticatedUser(user_id=str(user.id), email=user.email or "")


async def recovery_user(request: Request, user: User = Depends(current_auth_user)) -> User:
    if not pkce.recovery_grant(request, user.id):
        raise AuthError(403, "A verified, unexpired password recovery session is required")
    return user


async def handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
    code = {
        401: "unauthorized",
        403: "forbidden",
        415: "unsupported_media_type",
        429: "rate_limited",
        503: "service_unavailable",
    }.get(exc.status, "auth_error")
    response = JSONResponse(status_code=exc.status, content={"error": {"code": code, "message": exc.message}})
    if exc.clear_cookies:
        settings = request.app.state.auth_settings
        clear_session(response, settings)
        if request.url.path == "/auth/logout":
            pkce.cancel_pending(request, response)
    return response


def register_auth(app: FastAPI, settings: AuthSettings | None = None) -> None:
    """Wires auth state, CORS, middleware and the AuthError handler. Route
    declarations themselves live in main.py, not here. `settings` is
    overridable so tests can inject synthetic config without env vars."""
    settings = settings or AuthSettings.from_env()
    app.state.auth_settings = settings

    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, pkce.CallbackAccessFilter) for f in logger.filters):
        logger.addFilter(pkce.CallbackAccessFilter())

    app.add_exception_handler(AuthError, handle_auth_error)

    # Cookies require allow_credentials=True and an explicit (non-wildcard)
    # origin list — this is the one CORS policy for the whole app.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.trusted_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID", "X-CSRF-Protection", "Idempotency-Key", "Last-Event-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def auth_response_security(request: Request, call_next):
        is_auth = request.url.path.startswith("/auth/")
        supplied_origin = request.headers.get("origin")
        current_settings = request.app.state.auth_settings
        if is_auth and supplied_origin and supplied_origin not in current_settings.trusted_origins:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "forbidden", "message": "Origin is not allowed."}},
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if is_auth or getattr(request.state, "authenticated", False):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.add_middleware(pkce.CallbackRedactionMiddleware)
