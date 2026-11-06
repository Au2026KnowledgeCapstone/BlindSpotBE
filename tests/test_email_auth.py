"""PKCE integration tests with a single-use mocked Supabase code exchange."""
import base64
import asyncio
import hashlib
import json
import logging
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from backend import auth_pkce as pkce
from test_auth import make_app, USER, USER2, CREDENTIALS, HEADERS, session


class EmailAuthentication(unittest.TestCase):
    def setUp(self):
        self.calls, self.codes, self.used, self.sessions = [], {}, set(), {}
        self.outage, self.reject_reset, self.counter = False, False, 0
        def provider(request):
            self.calls.append(request)
            if self.outage:
                return httpx.Response(503, json={})
            body = json.loads(request.content) if request.content else {}
            if request.url.path.endswith(('/signup', '/recover')):
                purpose = 'signup' if request.url.path.endswith('/signup') else 'recovery'
                self.counter += 1
                self.codes[f'code-{self.counter}'] = {
                    'challenge': body['code_challenge'], 'purpose': purpose,
                    'callback': request.url.params['redirect_to'],
                }
                return httpx.Response(400 if self.reject_reset else 200, json=USER if purpose == 'signup' else {})
            if request.url.path.endswith('/token'):
                grant = request.url.params['grant_type']
                if grant == 'pkce':
                    code = body['auth_code']
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).rstrip(b'=').decode()
                    if code in self.used or code not in self.codes or self.codes[code]['challenge'] != challenge:
                        return httpx.Response(400, json={'msg': 'private failure'})
                    self.used.add(code)
                self.counter += 1
                data = session(suffix=str(self.counter))
                self.sessions[data['access_token']] = data
                return httpx.Response(200, json=data)
            if request.url.path.endswith('/user'):
                token = request.headers.get('authorization', '').removeprefix('Bearer ')
                data = self.sessions.get(token)
                if not data:
                    return httpx.Response(401, json={})
                return httpx.Response(200, json=data['user'])
            return httpx.Response(204)
        self.app = make_app(provider)
        self.client = TestClient(self.app, base_url='http://localhost:8000', follow_redirects=False)

    def post(self, path, body, client=None):
        return (client or self.client).post('/auth/' + path, json=body, headers=HEADERS)

    def start(self, purpose, client=None):
        client = client or self.client
        response = self.post('signup' if purpose == 'signup' else 'password/reset-request',
                             CREDENTIALS if purpose == 'signup' else {'email': CREDENTIALS['email']}, client)
        self.assertEqual(response.status_code, 200)
        code = f'code-{self.counter}'
        flow = self.codes[code]
        identifier = urlsplit(flow['callback']).path.rsplit('/', 1)[1]
        name = pkce.prefix(self.app.state.auth_settings) + identifier
        return {**flow, 'id': identifier, 'code': code, 'cookie': client.cookies[name], 'name': name,
                'response': response}

    def complete(self, flow, *, client=None, code=None):
        return (client or self.client).get(flow['callback'], params={'code': code or flow['code']})

    def test_signup_confirmation_uses_s256_without_returning_verifier_or_session(self):
        flow = self.start('signup')
        response = flow['response']
        self.assertEqual(response.json(), {'user':None, 'authenticated':False, 'confirmation_required':True})
        self.assertNotIn('bs_access', self.client.cookies)
        self.assertIn('/auth/callback/signup/', flow['callback'])
        raw = pkce.unseal(self.app.state.auth_settings, flow['cookie'].strip('"'))
        self.assertEqual(raw['purpose'], 'signup')
        self.assertNotIn(raw['verifier'], response.text)
        self.assertNotIn(raw['verifier'], flow['cookie'].strip('"'))
        self.assertEqual(json.loads(self.calls[-1].content)['code_challenge_method'], 's256')
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=lax', response.headers['set-cookie'])

    def test_successful_signup_exchanges_only_backend_and_redirects_clean(self):
        flow = self.start('signup')
        response = self.complete(flow)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], 'http://localhost:3000/login')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(response.content, b'')
        self.assertNotIn(flow['name'], self.client.cookies)
        self.assertIn('bs_access', self.client.cookies)
        self.assertNotIn('bs_recovery', self.client.cookies)
        exchange = self.calls[-1]
        self.assertEqual(exchange.url.params['grant_type'], 'pkce')
        self.assertEqual(json.loads(exchange.content)['auth_code'], flow['code'])
        self.assertNotIn(flow['code'], str(exchange.url))
        self.assertEqual(self.client.get('/auth/me').status_code, 200)
        self.assertEqual(self.client.get('/auth/recovery').status_code, 403)

    def test_missing_cookie_other_browser_and_expired_transaction_fail_without_exchange(self):
        flow = self.start('recovery')
        other = TestClient(self.app, base_url='http://localhost:8000', follow_redirects=False)
        before = len(self.calls)
        response = self.complete(flow, client=other)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], 'http://localhost:3000/reset-password')
        self.assertEqual(len(self.calls), before)
        self.assertFalse(list(other.cookies))
        with patch('backend.auth_pkce.time.time', return_value=time.time() + pkce.FLOW_TTL + 1):
            response = self.complete(flow)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.calls), before)
        self.assertNotIn(flow['name'], self.client.cookies)
        self.assertNotIn('bs_access', self.client.cookies)

    def test_overlapping_requests_have_independent_verifiers_and_cleanup(self):
        first, second = self.start('signup'), self.start('recovery')
        self.assertNotEqual(first['name'], second['name'])
        self.assertNotEqual(first['challenge'], second['challenge'])
        self.complete(second)
        self.assertIn(first['name'], self.client.cookies)
        self.assertNotIn(second['name'], self.client.cookies)
        self.assertEqual(self.client.get('/auth/recovery').status_code, 200)
        self.complete(first)
        self.assertNotIn(first['name'], self.client.cookies)
        self.assertEqual(self.client.get('/auth/me').status_code, 200)
        self.assertEqual(self.client.get('/auth/recovery').status_code, 403)

    def test_wrong_purpose_and_tampered_cookie_fail_before_exchange(self):
        flow = self.start('signup')
        before = len(self.calls)
        response = self.client.get(flow['callback'].replace('/signup/', '/recovery/'), params={'code':flow['code']})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.calls), before)
        flow = self.start('recovery')
        self.client.cookies.set(flow['name'], flow['cookie']+'tampered', domain='localhost.local', path='/')
        before = len(self.calls)
        self.complete(flow)
        self.assertEqual(len(self.calls), before)
        self.assertNotIn('bs_access', self.client.cookies)

    def test_invalid_reused_and_mismatched_codes_never_create_a_session(self):
        flow = self.start('signup')
        response = self.complete(flow, code='invalid-code')
        self.assertEqual(response.status_code, 303)
        self.assertNotIn('bs_access', self.client.cookies)
        first, second = self.start('signup'), self.start('signup')
        self.complete(first, code=second['code'])
        self.assertNotIn('bs_access', self.client.cookies)
        self.complete(second)
        self.client.cookies.clear()
        self.client.cookies.set(second['name'], second['cookie'], domain='localhost.local', path='/')
        self.complete(second)
        self.assertNotIn('bs_access', self.client.cookies)

    def test_untrusted_redirect_queries_are_not_followed_and_codes_not_reflected(self):
        flow = self.start('signup')
        response = self.client.get(flow['callback'], params={'code':flow['code'], 'next':'https://evil.example'})
        self.assertEqual(response.headers['location'], 'http://localhost:3000/login')
        self.assertNotIn('evil.example', response.text)
        self.assertNotIn(flow['code'], response.text)
        self.assertEqual(response.request.url.params['code'], flow['code'])

    def test_duplicate_codes_provider_errors_and_callback_outage_fail_clean(self):
        for query in ('code=one&code=two', 'code=x&error=bad&error_description=private'):
            flow = self.start('recovery')
            before = len(self.calls)
            response = self.client.get(flow['callback']+'?'+query)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(len(self.calls), before)
            self.assertNotIn('private', response.text)
        flow = self.start('recovery')
        self.outage = True
        response = self.complete(flow)
        self.assertEqual(response.status_code, 303)
        self.assertNotIn('bs_access', self.client.cookies)
        self.assertNotIn(flow['name'], self.client.cookies)

    def test_password_update_requires_recovery_not_ordinary_authenticated_session(self):
        self.assertEqual(self.post('password/update', {'password':'Synthetic-new-pass-2!'}).status_code, 401)
        self.post('login', CREDENTIALS)
        self.assertEqual(self.client.get('/auth/me').status_code, 200)
        self.assertEqual(self.post('password/update', {'password':'Synthetic-new-pass-2!'}).status_code, 403)
        self.assertFalse(any(r.method == 'PUT' for r in self.calls))

    def test_recovery_permission_bound_to_session_and_expires(self):
        self.complete(self.start('recovery'))
        self.assertEqual(self.client.get('/auth/recovery').status_code, 200)
        marker = self.client.cookies['bs_recovery']
        self.post('login', CREDENTIALS)
        self.client.cookies.set('bs_recovery', marker, domain='localhost.local', path='/')
        self.assertEqual(self.client.get('/auth/recovery').status_code, 403)
        self.complete(self.start('recovery'))
        with patch('backend.auth_pkce.time.time', return_value=time.time() + pkce.RECOVERY_TTL + 1):
            self.assertEqual(self.client.get('/auth/recovery').status_code, 403)

    def test_recovery_permission_survives_refresh_without_extending_expiry(self):
        self.complete(self.start('recovery'))
        settings = self.app.state.auth_settings
        original = pkce.unseal(settings, self.client.cookies['bs_recovery'].strip('"'))
        self.client.cookies.delete('bs_access', domain='localhost.local', path='/')
        self.assertEqual(self.post('refresh', {}).status_code, 200)
        renewed = pkce.unseal(settings, self.client.cookies['bs_recovery'].strip('"'))
        self.assertEqual(original['exp'], renewed['exp'])
        self.assertNotEqual(original['access'], renewed['access'])
        self.assertEqual(self.client.get('/auth/recovery').status_code, 200)

    def test_password_update_clears_session_and_pending_transactions(self):
        self.complete(self.start('recovery'))
        pending = self.start('signup')
        response = self.post('password/update', {'password':'Synthetic-new-pass-2!'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Synthetic-new-pass', response.text)
        self.assertFalse(list(self.client.cookies))
        self.assertEqual(self.client.get('/auth/recovery').status_code, 401)
        self.assertTrue(any(r.method == 'PUT' for r in self.calls))

    def test_logout_cancels_pending_links_and_recovery_permission(self):
        self.complete(self.start('recovery'))
        flow = self.start('signup')
        self.assertEqual(self.post('logout', {}).status_code, 200)
        before = len(self.calls)
        self.complete(flow)
        self.assertEqual(len(self.calls), before)
        self.assertFalse(list(self.client.cookies))

    def test_reset_request_generic_and_csrf_unchanged(self):
        first = self.start('recovery')['response']
        self.reject_reset = True
        second = self.start('recovery')['response']
        self.assertEqual(first.json(), second.json())
        self.assertEqual(self.client.post('/auth/password/reset-request', json={'email':CREDENTIALS['email']}).status_code, 403)
        self.assertEqual(self.client.post('/auth/password/update', json={'password':'Synthetic-new-pass-2!'}).status_code, 403)

    def test_pending_limit_and_missing_key_fail_closed(self):
        for _ in range(pkce.MAX_PENDING):
            self.start('recovery')
        self.assertEqual(self.post('password/reset-request', {'email':CREDENTIALS['email']}).status_code, 429)
        from dataclasses import replace
        self.client.cookies.clear()
        self.app.state.auth_settings = replace(self.app.state.auth_settings, flow_encryption_key='')
        self.assertEqual(self.post('signup', CREDENTIALS).status_code, 503)
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 200)

    def test_production_transaction_cookie_is_secure_host_only_and_http_only(self):
        app = make_app(lambda r: httpx.Response(200, json=USER), production=True)
        client = TestClient(app, base_url='https://backend.example.com')
        response = client.post('/auth/signup', json=CREDENTIALS,
                               headers={**HEADERS, 'Origin':'https://frontend.example.com'})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie']
        for attribute in ('__Host-bs_pkce_', 'Secure', 'HttpOnly', 'Path=/', 'SameSite=lax', 'Max-Age=900'):
            self.assertIn(attribute, cookie)
        self.assertNotIn('Domain=', cookie)

    def test_recovery_identity_must_match_the_server_issued_grant(self):
        self.complete(self.start('recovery'))
        token = self.client.cookies['bs_access']
        self.sessions[token]['user'] = USER2
        self.assertEqual(self.client.get('/auth/recovery').status_code, 403)
        self.assertEqual(self.post('password/update', {'password':'Synthetic-new-pass-2!'}).status_code, 403)

    def test_asgi_redaction_removes_query_even_before_route_validation(self):
        captured = {}
        async def capture(scope, receive, send):
            captured.update(scope)
        scope = {'type':'http', 'path':'/auth/callback/signup/example',
                 'query_string':b'code=synthetic-private-code&error_description=do-not-log'}
        asyncio.run(pkce.CallbackRedactionMiddleware(capture)(scope, None, None))
        self.assertEqual(captured['query_string'], b'')
        self.assertIsNone(captured['state']['pkce_code'])

    def test_access_log_filter_redacts_callback_codes_and_transaction_path(self):
        record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s - "%s %s HTTP/%s" %d',
                                   ('127.0.0.1', 'GET', '/auth/callback/signup/private-id?code=private-code', '1.1', 303), None)
        pkce.CallbackAccessFilter().filter(record)
        self.assertNotIn('private', record.getMessage())
        self.assertIn('[redacted]', record.getMessage())
