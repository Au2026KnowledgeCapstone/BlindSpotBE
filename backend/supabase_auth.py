"""Stateless Supabase Auth REST adapter: no shared cookies or auth sessions."""
import httpx
from fastapi import Request
from pydantic import ValidationError

from backend.auth_schemas import User


class AuthError(Exception):
    def __init__(self, status: int, message: str, clear_cookies: bool = False):
        self.status = status
        self.message = message
        self.clear_cookies = clear_cookies


async def supabase_request(request: Request, method: str, path: str, *, body=None,
                           token: str | None = None, params=None, invalid_status=401):
    settings = request.app.state.auth_settings
    if not settings.supabase_url or not settings.publishable_key:
        raise AuthError(503, 'Authentication service is not configured')
    headers = {'apikey': settings.publishable_key}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    # A new client for each call prevents cross-user headers/cookie/session leakage.
    transport = getattr(request.app.state, 'supabase_transport', None)
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport, follow_redirects=False,
                                     trust_env=False) as client:
            response = await client.request(method, settings.supabase_url + '/auth/v1' + path,
                                            headers=headers, json=body, params=params)
    except httpx.RequestError:
        raise AuthError(503, 'Authentication service is unavailable') from None
    if response.status_code == 429:
        raise AuthError(429, 'Too many authentication attempts; try again later')
    if response.status_code >= 500:
        raise AuthError(503, 'Authentication service is unavailable')
    if response.status_code in {400, 401, 403, 422}:
        # Never expose upstream bodies or distinguish whether an account exists.
        raise AuthError(invalid_status, 'Authentication request was rejected')
    if not 200 <= response.status_code < 300:
        raise AuthError(503, 'Unexpected authentication service response')
    if response.status_code == 204:
        return {}
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise AuthError(503, 'Invalid authentication service response') from None


def verified_user(data):
    try:
        return User.model_validate(data)
    except (ValidationError, TypeError):
        raise AuthError(503, 'Invalid authentication service response') from None
