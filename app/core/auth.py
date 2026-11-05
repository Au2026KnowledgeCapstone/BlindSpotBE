"""The auth seam.

`TokenVerifier` is owned by whoever implements real backend token
verification — not by this module. The real implementation must verify the
token's signature, expiry, and audience against the Supabase project. Do not
add a JWT library or JWKS fetching here; `DevTokenVerifier` below is a
placeholder for local development only.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from fastapi import Header
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.errors import ServiceError

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str  # the Supabase `sub` claim
    email: str


class AuthenticationError(Exception):
    """Raised by a TokenVerifier when a token is missing, malformed, or
    invalid. current_user turns this into a 401 without ever distinguishing
    why."""


class TokenVerifier(Protocol):
    # Implemented by whoever owns token verification. Not by this handoff.
    def verify(self, bearer_token: str) -> AuthenticatedUser: ...


class DevTokenVerifier:
    """Local-development stand-in. Accepts any bearer value and returns a
    fixed user id read from DEV_AUTH_USER_ID.

    Impossible to leave on by accident: unset, every authenticated request
    is 401 with no default user; set against a non-local database, the
    application refuses to start.
    """

    def __init__(self) -> None:
        settings = get_settings()
        if settings.dev_auth_user_id:
            host = make_url(settings.database_url).host or ""
            if host.lower() not in _LOCAL_HOSTS:
                raise RuntimeError(
                    f"DEV_AUTH_USER_ID is set but the configured database host "
                    f"({host!r}) is not localhost. Refusing to start."
                )

    def verify(self, bearer_token: str) -> AuthenticatedUser:
        settings = get_settings()
        if not settings.dev_auth_user_id:
            raise AuthenticationError("DEV_AUTH_USER_ID is not set.")
        return AuthenticatedUser(
            user_id=settings.dev_auth_user_id,
            email=f"{settings.dev_auth_user_id}@dev.local",
        )


@lru_cache
def get_token_verifier() -> TokenVerifier:
    return DevTokenVerifier()


async def current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ServiceError("unauthorized", "Authentication required.", status_code=401)

    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise ServiceError("unauthorized", "Authentication required.", status_code=401)

    verifier = get_token_verifier()
    try:
        return verifier.verify(token)
    except Exception as exc:
        raise ServiceError("unauthorized", "Authentication required.", status_code=401) from exc
