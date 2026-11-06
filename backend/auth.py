"""Cookie authentication; feature authorization is deliberately not applied here."""
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
import logging
from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, SecretStr, ValidationError

from backend.auth_schemas import AuthResult, Credentials, EmptyRequest, Message, SignupCredentials, User, ResetRequest, PasswordUpdate
from backend.config import AuthSettings
from backend.supabase_auth import AuthError, supabase_request, verified_user

from backend import auth_pkce as pkce

router = APIRouter(prefix='/auth', tags=['Authentication'])


def clear_session(response: Response, settings: AuthSettings):
    for name in (settings.access_cookie, settings.refresh_cookie, pkce.recovery_name(settings)):
        response.delete_cookie(name, path='/', secure=settings.secure,
                               httponly=True, samesite=settings.same_site)


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
        raise AuthError(503, 'Invalid authentication service response') from None
    for name, value, age in (
        (settings.access_cookie, session.access_token.get_secret_value(), session.expires_in),
        (settings.refresh_cookie, session.refresh_token.get_secret_value(), settings.refresh_max_age),
    ):
        response.set_cookie(name, value, max_age=age,
                            expires=datetime.now(timezone.utc) + timedelta(seconds=age),
                            path='/', secure=settings.secure, httponly=True,
                            samesite=settings.same_site)
    pkce.delete_cookie(response, settings, pkce.recovery_name(settings))
    return session.user


async def csrf_guard(request: Request, x_csrf_protection: Annotated[
        str | None, Header(description="Required value: 1. Also send an allowed Origin and application/json.")
] = None):
    # Exact Origin + a non-simple custom header is an explicit CSRF protocol,
    # including before login. CORS alone is not the security boundary.
    settings = request.app.state.auth_settings
    if (request.headers.get('origin') not in settings.trusted_origins
            or x_csrf_protection != '1'
            or request.headers.get('sec-fetch-site') == 'cross-site' and settings.same_site != 'none'):
        raise AuthError(403, 'Origin or CSRF check failed')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise AuthError(415, 'Use application/json')


async def current_user(request: Request) -> User:
    settings = request.app.state.auth_settings
    token = request.cookies.get(settings.access_cookie)
    if not token:
        raise AuthError(401, 'Authentication required')
    # Supabase checks authenticity; we never decode an unverified JWT.
    try:
        data = await supabase_request(request, 'GET', '/user', token=token)
    except AuthError as exc:
        if exc.status == 401:
            exc.message = 'Invalid or expired session'
        raise
    return verified_user(data)


@router.post('/signup', response_model=AuthResult, dependencies=[Depends(csrf_guard)])
async def signup(credentials: SignupCredentials, request: Request, response: Response):
    email_destination(request, 'email')
    transaction = pkce.new_transaction(request, 'signup')
    data = await supabase_request(request, 'POST', '/signup', body={
        'email': str(credentials.email), 'password': credentials.password.get_secret_value(),
        'code_challenge': transaction['challenge'], 'code_challenge_method': 's256',
    }, params={'redirect_to': transaction['callback']}, invalid_status=400)
    if data.get('access_token'):
        user = set_session(response, data, request.app.state.auth_settings)
        return AuthResult(user=user, authenticated=True)
    verified_user(data.get("user", data))
    # Confirmation-enabled signup (including obfuscated existing-user replies).
    # Do not echo an unconfirmed identity or overwrite another logged-in session.
    pkce.persist_transaction(request, response, transaction)
    return AuthResult(authenticated=False, confirmation_required=True)


@router.post('/login', response_model=AuthResult, dependencies=[Depends(csrf_guard)])
async def login(credentials: Credentials, request: Request, response: Response):
    data = await supabase_request(request, 'POST', '/token', params={'grant_type': 'password'}, body={
        'email': str(credentials.email), 'password': credentials.password.get_secret_value(),
    })
    user = set_session(response, data, request.app.state.auth_settings)
    return AuthResult(user=user, authenticated=True)


@router.get('/me', response_model=User)
async def me(user: User = Depends(current_user)):
    return user


@router.post('/refresh', response_model=AuthResult, dependencies=[Depends(csrf_guard)])
async def refresh(payload: EmptyRequest, request: Request, response: Response):
    settings = request.app.state.auth_settings
    recovery = pkce.recovery_grant(request, refreshing=True)
    token = request.cookies.get(settings.refresh_cookie)
    if not token:
        raise AuthError(401, 'Authentication required', clear_cookies=True)
    try:
        data = await supabase_request(request, 'POST', '/token', params={'grant_type': 'refresh_token'},
                                      body={'refresh_token': token})
    except AuthError as exc:
        # Keep cookies on outages so a retry can recover the session.
        exc.clear_cookies = exc.status == 401
        raise
    user = set_session(response, data, settings)
    if recovery and recovery.get('sub') == str(user.id):
        pkce.set_recovery(request, response, data, user, expires=recovery['exp'])
    return AuthResult(user=user, authenticated=True)


@router.post('/logout', response_model=Message, dependencies=[Depends(csrf_guard)])
async def logout(payload: EmptyRequest, request: Request, response: Response):
    settings = request.app.state.auth_settings
    token = request.cookies.get(settings.access_cookie)
    refresh_token = request.cookies.get(settings.refresh_cookie)
    try:
        # Access cookie may already have expired. Rotate once to revoke the
        # remaining refresh session instead of silently abandoning it.
        if not token and refresh_token:
            data = await supabase_request(request, 'POST', '/token', params={'grant_type': 'refresh_token'},
                                          body={'refresh_token': refresh_token})
            token = data.get('access_token')
            if not isinstance(token, str) or not token:
                raise AuthError(503, 'Invalid authentication service response')
        if token:
            try:
                await supabase_request(request, 'POST', '/logout', token=token, params={'scope': 'local'})
            except AuthError as exc:
                if exc.status != 401 or not refresh_token:
                    raise
                # A stale access cookie must not leave a valid refresh session
                # behind. Refresh with Supabase before retrying revocation.
                data = await supabase_request(request, 'POST', '/token',
                                              params={'grant_type': 'refresh_token'},
                                              body={'refresh_token': refresh_token})
                token = data.get('access_token')
                if not isinstance(token, str) or not token:
                    raise AuthError(503, 'Invalid authentication service response')
                await supabase_request(request, 'POST', '/logout', token=token, params={'scope': 'local'})
    except AuthError as exc:
        if exc.status != 401:
            exc.clear_cookies = True
            raise
    clear_session(response, settings)
    pkce.cancel_pending(request, response)
    return Message(message='Signed out of this session')



def email_destination(request: Request, kind: str) -> str:
    settings = request.app.state.auth_settings
    origin = settings.email_frontend_origin
    if not origin and len(settings.frontend_origins) == 1:
        origin = settings.frontend_origins[0]
    if not origin:
        raise AuthError(503, 'Email authentication destination is not configured')
    return origin + ('/login' if kind == 'email' else '/reset-password')


@router.get('/callback/{purpose}/{transaction_id}', status_code=303, response_class=RedirectResponse)
async def pkce_callback(purpose: Literal['signup', 'recovery'], transaction_id: str, request: Request):
    settings = request.app.state.auth_settings
    destination = email_destination(request, 'email' if purpose == 'signup' else 'recovery')
    response = RedirectResponse(destination, status_code=303)
    # Clear the chosen transaction on every outcome; never reflect provider errors.
    if pkce.FLOW_ID.fullmatch(transaction_id):
        pkce.delete_cookie(response, settings, pkce.prefix(settings) + transaction_id, transaction=True)
    pkce.delete_cookie(response, settings, pkce.recovery_name(settings))
    try:
        pending = pkce.transaction(request, purpose, transaction_id)
    except AuthError:
        return response
    code = getattr(request.state, 'pkce_code', None)
    if not pending or not code:
        return response
    try:
        data = await supabase_request(request, 'POST', '/token', params={'grant_type': 'pkce'},
                                      body={'auth_code': code, 'code_verifier': pending['verifier']})
        user = set_session(response, data, settings)
        if purpose == 'recovery':
            pkce.set_recovery(request, response, data, user)
    except AuthError:
        # Signup confirmation may already have succeeded at Supabase. The clean
        # login page remains available; recovery never falls back to ordinary login.
        pass
    return response


async def recovery_user(request: Request, user: User = Depends(current_user)) -> User:
    if not pkce.recovery_grant(request, user.id):
        raise AuthError(403, 'A verified, unexpired password recovery session is required')
    return user


@router.get('/recovery', response_model=User)
async def recovery_status(user: User = Depends(recovery_user)):
    return user


@router.post('/password/reset-request', response_model=Message, dependencies=[Depends(csrf_guard)])
async def password_reset_request(payload: ResetRequest, request: Request, response: Response):
    email_destination(request, 'recovery')
    transaction = pkce.new_transaction(request, 'recovery')
    try:
        await supabase_request(request, 'POST', '/recover', body={'email': str(payload.email),
                                     'code_challenge': transaction['challenge'], 'code_challenge_method': 's256'},
                               params={'redirect_to': transaction['callback']}, invalid_status=400)
    except AuthError as exc:
        # Match successful/existing/nonexistent-account requests without exposing
        # provider account distinctions. Operational outages remain distinguishable.
        if exc.status not in {400, 429}:
            raise
    pkce.persist_transaction(request, response, transaction)
    return Message(message='If an account exists for this email, a password reset link will be sent.')


@router.post('/password/update', response_model=Message, dependencies=[Depends(csrf_guard)])
async def password_update(payload: PasswordUpdate, request: Request, response: Response,
                          user: User = Depends(recovery_user)):
    token = request.cookies[request.app.state.auth_settings.access_cookie]
    await supabase_request(request, 'PUT', '/user', token=token,
                           body={'password': payload.password.get_secret_value()}, invalid_status=400)
    # Password update succeeded. Do not misreport failure if subsequent revocation
    # is unavailable; disclose that outcome without exposing credentials.
    message = 'Password updated. Sign in again.'
    try:
        await supabase_request(request, 'POST', '/logout', token=token, params={'scope': 'local'})
    except AuthError:
        message = 'Password updated. Local session cleared; remote session revocation could not be confirmed.'
    clear_session(response, request.app.state.auth_settings)
    pkce.cancel_pending(request, response)
    return Message(message=message)


def install_auth(app: FastAPI, settings: AuthSettings | None = None):
    settings = settings or AuthSettings.from_env()
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, pkce.CallbackAccessFilter) for f in logger.filters):
        logger.addFilter(pkce.CallbackAccessFilter())
    app.state.auth_settings = settings
    app.include_router(router)

    @app.exception_handler(AuthError)
    async def handle_auth_error(request: Request, exc: AuthError):
        response = JSONResponse({'detail': exc.message}, status_code=exc.status,
                                headers={'Cache-Control': 'no-store'})
        if exc.clear_cookies:
            clear_session(response, settings)
            if request.url.path == '/auth/logout':
                pkce.cancel_pending(request, response)
        return response

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith('/auth/'):
            # FastAPI's default validation response includes rejected input,
            # which could contain a password/token. Return only a fixed message.
            return JSONResponse({'detail': 'Invalid authentication request'}, status_code=422,
                                headers={'Cache-Control': 'no-store'})
        return await request_validation_exception_handler(request, exc)

    # CORS must run outside the pre-existing automatic OPTIONS middleware.
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.trusted_origins),
                       allow_credentials=True, allow_methods=['GET', 'POST', 'PATCH', 'HEAD', 'OPTIONS'],
                       allow_headers=['Content-Type', 'X-CSRF-Protection'])

    @app.middleware('http')
    async def auth_response_security(request: Request, call_next):
        is_auth = request.url.path.startswith('/auth/')
        supplied_origin = request.headers.get('origin')
        if is_auth and supplied_origin and supplied_origin not in settings.trusted_origins:
            return JSONResponse({'detail': 'Origin is not allowed'}, status_code=403,
                                headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        if is_auth or getattr(request.state, 'feature_session_verified', False):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app.add_middleware(pkce.CallbackRedactionMiddleware)
