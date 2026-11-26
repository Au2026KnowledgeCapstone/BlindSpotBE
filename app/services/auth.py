"""Auth logic too long for a thin main.py handler (the ~15-line rule).
Ported from feat/backend-auth (backend/auth.py) — relocated, not rewritten."""
from fastapi import Request, Response

from app.core import auth_pkce as pkce
from app.core.auth import VerifiedRecovery, clear_session, email_destination, set_session, validate_session
from app.core.supabase_auth import AuthError, supabase_request, verified_user
from app.schemas.auth import (
    AuthResult, EmailRequest, Message, PasswordUpdate, ResetRequest, SignupAuthenticated,
    SignupConfirmationRequired, SignupCredentials, SignupResult,
)


async def signup_session(request: Request, response: Response, credentials: SignupCredentials) -> SignupResult:
    email_destination(request, "email")
    transaction = pkce.new_transaction(request, "signup")
    try:
        data = await supabase_request(
            request, "POST", "/signup",
            body={
                "email": str(credentials.email), "password": credentials.password.get_secret_value(),
                "code_challenge": transaction["challenge"], "code_challenge_method": "s256",
            },
            params={"redirect_to": transaction["callback"]}, invalid_status=400,
        )
    except AuthError as exc:
        duplicate = exc.provider_status in {400, 422} and exc.provider_code in {"user_already_exists", "email_exists"}
        email_cooldown = exc.provider_status == 429 and exc.provider_code == "over_email_send_rate_limit"
        if not (duplicate or email_cooldown):
            raise
    else:
        if data.get("access_token") is not None or data.get("refresh_token") is not None:
            user = set_session(response, data, request.app.state.auth_settings)
            return SignupAuthenticated(user=user)
        verified_user(data.get("user", data))
    # Use the same public result and transaction cookie for all pending outcomes.
    pkce.persist_transaction(request, response, transaction)
    return SignupConfirmationRequired()


async def resend_confirmation(request: Request, response: Response, payload: EmailRequest) -> Message:
    email_destination(request, "email")
    transaction = pkce.new_transaction(request, "signup")
    try:
        await supabase_request(
            request, "POST", "/resend",
            body={
                "type": "signup", "email": str(payload.email),
                "code_challenge": transaction["challenge"], "code_challenge_method": "s256",
            },
            params={"redirect_to": transaction["callback"]}, invalid_status=400,
        )
    except AuthError as exc:
        request_limited = exc.provider_status == 429 and exc.provider_code == "over_request_rate_limit"
        if exc.provider_status is None or request_limited:
            raise
        # Delivery errors and per-address cooldowns may occur only for eligible addresses.
        # Leave the provider's send limits in force while returning the same receipt.
    pkce.persist_transaction(request, response, transaction)
    return Message(message="If confirmation is still needed, check your email for a link.")


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
        # Delivery failures and address-specific throttles may occur only for
        # eligible accounts. Surface transport failures and request-wide limits.
        request_limited = exc.provider_status == 429 and exc.provider_code == "over_request_rate_limit"
        if exc.provider_status is None or request_limited:
            raise
    pkce.persist_transaction(request, response, transaction)
    return Message(message="If this address is eligible for password reset, check your email for a link.")


async def refresh_session(request: Request, response: Response) -> AuthResult:
    settings = request.app.state.auth_settings
    token = request.cookies.get(settings.refresh_cookie)
    if not token:
        raise AuthError(401, "Authentication required", clear_cookies=True)
    if pkce.is_legacy_recovery(request):
        raise AuthError(401, "Authentication required", clear_cookies=True)
    try:
        data = await supabase_request(
            request, "POST", "/token", params={"grant_type": "refresh_token"}, body={"refresh_token": token}
        )
    except AuthError as exc:
        # Keep cookies on outages so a retry can recover the session.
        exc.clear_cookies = exc.status == 401
        raise
    user = set_session(response, data, settings, preserve_recovery=True)
    return AuthResult(user=user, authenticated=True)


async def revoke_workspace_session(request: Request) -> None:
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
            raise


async def logout_session(request: Request, response: Response) -> str:
    settings = request.app.state.auth_settings
    failure = None
    try:
        await revoke_workspace_session(request)
    except AuthError as exc:
        failure = exc
    try:
        recovery = pkce.recovery_grant(request)
        if recovery:
            await supabase_request(request, "POST", "/logout", token=recovery["access_token"], params={"scope": "local"})
    except AuthError as exc:
        if exc.status != 401:
            failure = failure or exc
    if failure:
        failure.clear_cookies = True
        raise failure
    clear_session(response, settings)
    pkce.cancel_pending(request, response)
    return "Signed out of this session"


async def update_password(request: Request, response: Response, payload: PasswordUpdate, recovery: VerifiedRecovery) -> str:
    settings = request.app.state.auth_settings
    if payload.user_id != recovery.user.id:
        raise AuthError(401, "The password reset session changed")
    token = recovery.access_token.get_secret_value()
    await supabase_request(
        request, "PUT", "/user", token=token, body={"password": payload.password.get_secret_value()}, invalid_status=400
    )
    # Password update succeeded. Do not misreport failure if subsequent revocation
    # is unavailable; disclose that outcome without exposing credentials.
    message = "Password updated. Sign in again."
    try:
        await supabase_request(request, "POST", "/logout", token=token, params={"scope": "local"})
    except AuthError:
        message = "Password updated. Reset access cleared in this browser. Remote revocation could not be confirmed."
    pkce.delete_cookie(response, settings, pkce.recovery_name(settings))
    pkce.cancel_pending(request, response)
    return message


async def complete_pkce_callback(request: Request, response: Response, purpose: str, transaction_id: str) -> str:
    settings = request.app.state.auth_settings
    # Clear the chosen transaction on every outcome; never reflect provider errors.
    if pkce.FLOW_ID.fullmatch(transaction_id):
        pkce.delete_cookie(response, settings, pkce.prefix(settings) + transaction_id, transaction=True)
    try:
        pending = pkce.transaction(request, purpose, transaction_id)
    except AuthError as exc:
        return "expired" if exc.status == 410 else "failed"
    if getattr(request.state, "pkce_expired", False):
        return "expired"
    code = getattr(request.state, "pkce_code", None)
    if not pending or not code:
        return "invalid"
    try:
        data = await supabase_request(
            request, "POST", "/token", params={"grant_type": "pkce"},
            body={"auth_code": code, "code_verifier": pending["verifier"]},
        )
        if purpose == "recovery":
            pkce.set_recovery(request, response, validate_session(data))
        elif request.cookies.get(settings.access_cookie) or request.cookies.get(settings.refresh_cookie):
            # Confirm the email without silently switching an existing browser session.
            validate_session(data)
        else:
            set_session(response, data, settings, preserve_recovery=True)
        return "confirmed"
    except AuthError as exc:
        return "expired" if exc.status == 410 else "failed"
