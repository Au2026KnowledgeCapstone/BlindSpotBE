"""Encrypted browser-bound PKCE transactions and session-bound recovery grants."""
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from urllib.parse import parse_qs, unquote

from cryptography.fernet import Fernet, InvalidToken

from backend.supabase_auth import AuthError

FLOW_TTL = 900
RECOVERY_TTL = 600
MAX_PENDING = 8
FLOW_ID = re.compile(r'^[A-Za-z0-9_-]{32}$')


def cipher(settings):
    if not settings.flow_encryption_key:
        raise AuthError(503, 'Email authentication encryption is not configured')
    try:
        return Fernet(settings.flow_encryption_key.encode())
    except (ValueError, TypeError):
        raise AuthError(503, 'Email authentication encryption is not configured') from None


def seal(settings, value):
    return cipher(settings).encrypt(json.dumps(value).encode()).decode()


def unseal(settings, value):
    try:
        if base64.urlsafe_b64encode(base64.urlsafe_b64decode(value)).decode() != value:
            return None
        result = json.loads(cipher(settings).decrypt(value.encode()))
        if not isinstance(result, dict) or not isinstance(result.get('exp'), int) or result['exp'] <= time.time():
            return None
        return result
    except (InvalidToken, ValueError, TypeError, AttributeError):
        return None


def prefix(settings):
    return 'bs_pkce_' if settings.development else '__Host-bs_pkce_'


def recovery_name(settings):
    return 'bs_recovery' if settings.development else '__Host-bs_recovery'


def write_cookie(response, settings, name, value, age, *, transaction=False):
    response.set_cookie(name, value, max_age=age, path='/', secure=settings.secure,
                        httponly=True, samesite='lax' if transaction else settings.same_site)


def delete_cookie(response, settings, name, *, transaction=False):
    response.delete_cookie(name, path='/', secure=settings.secure, httponly=True,
                           samesite='lax' if transaction else settings.same_site)


def cancel_pending(request, response):
    settings = request.app.state.auth_settings
    for name in request.cookies:
        if name.startswith(prefix(settings)):
            delete_cookie(response, settings, name, transaction=True)


def new_transaction(request, purpose):
    settings = request.app.state.auth_settings
    if not settings.backend_origin:
        raise AuthError(503, 'Backend callback origin is not configured')
    if sum(name.startswith(prefix(settings)) for name in request.cookies) >= MAX_PENDING:
        raise AuthError(429, 'Too many pending email requests; try again later')
    identifier = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    value = seal(settings, {'id': identifier, 'purpose': purpose, 'verifier': verifier,
                            'exp': int(time.time()) + FLOW_TTL})
    return {'id': identifier, 'value': value, 'challenge': challenge,
            'callback': settings.backend_origin + '/auth/callback/' + purpose + '/' + identifier}


def persist_transaction(request, response, transaction):
    settings = request.app.state.auth_settings
    write_cookie(response, settings, prefix(settings) + transaction['id'], transaction['value'],
                 FLOW_TTL, transaction=True)


def transaction(request, purpose, identifier):
    settings = request.app.state.auth_settings
    if not FLOW_ID.fullmatch(identifier):
        return None
    raw = request.cookies.get(prefix(settings) + identifier)
    if not raw:
        return None
    value = unseal(settings, raw)
    if (not value or value.get('id') != identifier or value.get('purpose') != purpose
            or not isinstance(value.get('verifier'), str)):
        return None
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def recovery_grant(request, user_id=None, *, refreshing=False):
    settings = request.app.state.auth_settings
    raw = request.cookies.get(recovery_name(settings))
    if not raw:
        return None
    value = unseal(settings, raw)
    if not value or value.get('purpose') != 'recovery':
        return None
    access = request.cookies.get(settings.access_cookie, '')
    # A refresh may replace an expired/missing access cookie only when the
    # encrypted grant still matches the refresh credential verified by Supabase.
    if (not refreshing or access) and value.get('access') != digest(access):
        return None
    if value.get('refresh') != digest(request.cookies.get(settings.refresh_cookie, '')):
        return None
    if user_id is not None and value.get('sub') != str(user_id):
        return None
    return value


def set_recovery(request, response, data, user, *, expires=None):
    settings = request.app.state.auth_settings
    expires = min(expires or int(time.time()) + RECOVERY_TTL,
                  int(time.time()) + int(data['expires_in']))
    age = expires - int(time.time())
    if age <= 0:
        return
    value = seal(settings, {'purpose': 'recovery', 'sub': str(user.id), 'exp': expires,
                            'access': digest(data['access_token']), 'refresh': digest(data['refresh_token'])})
    write_cookie(response, settings, recovery_name(settings), value, age)


class CallbackAccessFilter(logging.Filter):
    """Uvicorn access records contain a request target as argument 3."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if unquote(str(args[2])).startswith('/auth/callback/'):
                args[2] = '/auth/callback/[redacted]'
                record.args = tuple(args)
        return True


class CallbackRedactionMiddleware:
    """Strip callback query from ASGI scope before routing/logging, retain only code.

    The Uvicorn filter additionally hides the transaction ID in the access target.
    Proxy/hosting log redaction must be configured independently by the operator.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path', '').startswith('/auth/callback/'):
            raw = scope.get('query_string', b'')
            scope['query_string'] = b''
            try:
                values = parse_qs(raw.decode(), max_num_fields=12, keep_blank_values=True)
                codes = values.get('code', [])
                code = codes[0] if len(codes) == 1 and 0 < len(codes[0]) <= 512 else None
                if 'error' in values or 'error_description' in values:
                    code = None
            except (ValueError, UnicodeDecodeError):
                code = None
            scope.setdefault('state', {})['pkce_code'] = code
        await self.app(scope, receive, send)
