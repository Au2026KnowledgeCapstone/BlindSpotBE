"""Auth logic too long for a thin main.py handler (the ~15-line rule).
Ported from feat/backend-auth (backend/auth.py) — relocated, not rewritten."""
from fastapi import Request, Response

from app.core import auth_pkce as pkce
from app.core.auth import clear_session, email_destination, set_session
from app.core.supabase_auth import AuthError, supabase_request, verified_user
from app.schemas.auth import AuthResult, Message, PasswordUpdate, ResetRequest, SignupCredentials


async def signup_session(request: Request, response: Response, credentials: SignupCredentials) -> AuthResult:
    email_destination(request, "email")
    transaction = pkce.new_transaction(request, "signup")
    data = await supabase_request(
        request, "POST", "/signup",
        body={
            "email": str(credentials.email), "password": credentials.password.get_secret_value(),
            "code_challenge": transaction["challenge"], "code_challenge_method": "s256",
        },
        params={"redirect_to": transaction["callback"]}, invalid_status=400,
    )
    if data.get("access_token"):
        user = set_session(response, data, request.app.state.auth_settings)
        return AuthResult(user=user, authenticated=True)
    verified_user(data.get("user", data))
    # Confirmation-enabled signup (including obfuscated existing-user replies).
    # Do not echo an unconfirmed identity or overwrite another logged-in session.
    pkce.persist_transaction(request, response, transaction)
    return AuthResult(authenticated=False, confirmation_required=True)


async def request_password_reset(request: Request, response: Response, payload: ResetRequest) -> Message:
    email_destination(request, "recovery")
    transaction = pkce.new_transaction(request, "recovery")
    try:
        await supabase_request(
            request, "POST", "/recover",
            body={"email": str(payload.email), "code_challenge": transaction["challenge"], "code_challenge_method": "s256"},
            params={"redirect_to": transaction["callback"]}, invalid_status=400,
        )
    except AuthError as exc:
        # Match successful/existing/nonexistent-account requests without exposing
        # provider account distinctions. Operational outages remain distinguishable.
        if exc.status not in {400, 429}:
            raise
    pkce.persist_transaction(request, response, transaction)
    return Message(message="If an account exists for this email, a password reset link will be sent.")


async def refresh_session(request: Request, response: Response) -> AuthResult:
    settings = request.app.state.auth_settings
    recovery = pkce.recovery_grant(request, refreshing=True)
    token = request.cookies.get(settings.refresh_cookie)
    if not token:
        raise AuthError(401, "Authentication required", clear_cookies=True)
    try:
        data = await supabase_request(
            request, "POST", "/token", params={"grant_type": "refresh_token"}, body={"refresh_token": token}
        )
    except AuthError as exc:
        # Keep cookies on outages so a retry can recover the session.
        exc.clear_cookies = exc.status == 401
        raise
    user = set_session(response, data, settings)
    if recovery and recovery.get("sub") == str(user.id):
        pkce.set_recovery(request, response, data, user, expires=recovery["exp"])
    return AuthResult(user=user, authenticated=True)


async def logout_session(request: Request, response: Response) -> str:
    settings = request.app.state.auth_settings
    token = request.cookies.get(settings.access_cookie)
    refresh_token = request.cookies.get(settings.refresh_cookie)
    try:
        # Access cookie may already have expired. Rotate once to revoke the
        # remaining refresh session instead of silently abandoning it.
        if not token and refresh_token:
            data = await supabase_request(
                request, "POST", "/token", params={"grant_type": "refresh_token"}, body={"refresh_token": refresh_token}
            )
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise AuthError(503, "Invalid authentication service response")
        if token:
            try:
                await supabase_request(request, "POST", "/logout", token=token, params={"scope": "local"})
            except AuthError as exc:
                if exc.status != 401 or not refresh_token:
                    raise
                # A stale access cookie must not leave a valid refresh session
                # behind. Refresh with Supabase before retrying revocation.
                data = await supabase_request(
                    request, "POST", "/token", params={"grant_type": "refresh_token"}, body={"refresh_token": refresh_token}
                )
                token = data.get("access_token")
                if not isinstance(token, str) or not token:
                    raise AuthError(503, "Invalid authentication service response")
                await supabase_request(request, "POST", "/logout", token=token, params={"scope": "local"})
    except AuthError as exc:
        if exc.status != 401:
            exc.clear_cookies = True
            raise
    clear_session(response, settings)
    pkce.cancel_pending(request, response)
    return "Signed out of this session"


async def update_password(request: Request, response: Response, payload: PasswordUpdate) -> str:
    settings = request.app.state.auth_settings
    token = request.cookies[settings.access_cookie]
    await supabase_request(
        request, "PUT", "/user", token=token, body={"password": payload.password.get_secret_value()}, invalid_status=400
    )
    # Password update succeeded. Do not misreport failure if subsequent revocation
    # is unavailable; disclose that outcome without exposing credentials.
    message = "Password updated. Sign in again."
    try:
        await supabase_request(request, "POST", "/logout", token=token, params={"scope": "local"})
    except AuthError:
        message = "Password updated. Local session cleared; remote session revocation could not be confirmed."
    clear_session(response, settings)
    pkce.cancel_pending(request, response)
    return message


async def complete_pkce_callback(request: Request, response: Response, purpose: str, transaction_id: str) -> None:
    settings = request.app.state.auth_settings
    # Clear the chosen transaction on every outcome; never reflect provider errors.
    if pkce.FLOW_ID.fullmatch(transaction_id):
        pkce.delete_cookie(response, settings, pkce.prefix(settings) + transaction_id, transaction=True)
    pkce.delete_cookie(response, settings, pkce.recovery_name(settings))
    try:
        pending = pkce.transaction(request, purpose, transaction_id)
    except AuthError:
        return
    code = getattr(request.state, "pkce_code", None)
    if not pending or not code:
        return
    try:
        data = await supabase_request(
            request, "POST", "/token", params={"grant_type": "pkce"},
            body={"auth_code": code, "code_verifier": pending["verifier"]},
        )
        user = set_session(response, data, settings)
        if purpose == "recovery":
            pkce.set_recovery(request, response, data, user)
    except AuthError:
        # Signup confirmation may already have succeeded at Supabase. The clean
        # login page remains available; recovery never falls back to ordinary login.
        pass
