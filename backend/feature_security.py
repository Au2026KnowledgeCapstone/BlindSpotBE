"""Authentication boundary for feature scaffolding; not a project-access policy."""
from typing import Annotated

from fastapi import Depends, Header, Request

from backend.auth import csrf_guard, current_user
from backend.auth_schemas import User


async def feature_user(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    x_csrf_protection: Annotated[str | None, Header()] = None,
) -> User:
    # Identity verification must precede CSRF/body parsing: missing/invalid sessions
    # are 401, not a cookie-presence check or a client-controlled user/role field.
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        await csrf_guard(request, x_csrf_protection=x_csrf_protection)
    request.state.current_user = user
    request.state.feature_session_verified = True
    return user


FEATURE_SECURITY = {
    'dependencies': [Depends(feature_user)],
    'description': ('Requires a Supabase-verified backend cookie session; mutations also require '
                    'Origin, JSON and X-CSRF-Protection: 1. This handler remains a placeholder. '
                    'Project membership/ownership authorization is pending; authentication '
                    'alone does not approve access to real resources.'),
    'responses': {
        401: {'description': 'Missing or invalid verified backend session'},
        403: {'description': 'Cookie-authenticated mutation failed Origin/CSRF checks'},
        503: {'description': 'Session verification service unavailable'},
    },
}
