"""Narrow PostgREST adapter; all resources and query keys are chosen by routes."""
import httpx
from fastapi import Request

from app.core.errors import ServiceError


class AuthError(ServiceError):
    def __init__(self, status: int, message: str):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 415: "unsupported_media_type", 429: "rate_limited", 503: "service_unavailable"}.get(status, "workspace_error")
        super().__init__(code, message, status)


async def rest(request: Request, token: str, method: str, resource: str, *, params=None, body=None, count: str | None = None):
    settings = request.app.state.auth_settings
    if not token or not settings.supabase_url or not settings.publishable_key:
        raise AuthError(503, "Workspace service is unavailable")
    headers = {"apikey": settings.publishable_key, "Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
    if count:
        preference = f"count={count}"
        headers["Prefer"] = f"{headers['Prefer']},{preference}" if "Prefer" in headers else preference
    transport = getattr(request.app.state, "supabase_transport", None)
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport, follow_redirects=False, trust_env=False) as client:
            response = await client.request("POST" if method == "RPC" else method,
                f"{settings.supabase_url}/rest/v1/{resource}", headers=headers, params=params, json=body)
    except httpx.RequestError:
        raise AuthError(503, "Workspace service is unavailable") from None
    if response.status_code in {401, 403}:
        raise AuthError(response.status_code, "Workspace request was rejected")
    if response.status_code == 404:
        raise AuthError(404, "Workspace item not found")
    if response.status_code == 409:
        raise AuthError(409, "Workspace item already exists")
    if response.status_code == 429 or response.status_code >= 500 or not 200 <= response.status_code < 300:
        raise AuthError(503, "Workspace service is unavailable")
    if response.status_code == 204:
        return None
    request.state.upstream_content_range = response.headers.get("content-range")
    try:
        data = response.json()
    except ValueError:
        raise AuthError(503, "Invalid workspace service response") from None
    if not isinstance(data, (dict, list)):
        raise AuthError(503, "Invalid workspace service response")
    return data
