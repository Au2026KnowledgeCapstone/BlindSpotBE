"""Only synthetic credentials and mocked HTTP responses; never contact Supabase."""
import asyncio
import base64
import json
import unittest

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth import install_auth
from backend.config import AuthSettings

ORIGIN = 'http://localhost:3000'
HEADERS = {'Origin': ORIGIN, 'X-CSRF-Protection': '1', 'Content-Type': 'application/json'}
USER = {'id': '11111111-1111-4111-8111-111111111111', 'email': 'one@example.com',
        'user_metadata': {'role': 'admin'}, 'app_metadata': {'irrelevant': True}}
USER2 = {'id': '22222222-2222-4222-8222-222222222222', 'email': 'two@example.com'}
CREDENTIALS = {'email': 'one@example.com', 'password': 'Synthetic-pass-1!'}


def session(user=USER, suffix='one'):
    return {'access_token': f'access-{suffix}', 'refresh_token': f'refresh-{suffix}',
            'expires_in': 3600, 'user': user}


def make_app(handler, *, production=False):
    app = FastAPI()
    settings = AuthSettings(supabase_url='https://example.supabase.co',
                            publishable_key='synthetic-publishable-key',
                            flow_encryption_key=base64.urlsafe_b64encode(b'k' * 32).decode(),
                            development=not production,
                            frontend_origins=('https://frontend.example.com',) if production else (ORIGIN,),
                            backend_origin='https://backend.example.com' if production else 'http://localhost:8000')
    install_auth(app, settings)
    app.state.supabase_transport = httpx.MockTransport(handler)
    return app


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.reply = session()
        self.status = 200

        def handler(request):
            self.requests.append(request)
            return httpx.Response(self.status, json=self.reply) if self.status != 204 else httpx.Response(204)
        self.app = make_app(handler)
        self.client = TestClient(self.app, base_url='http://localhost:8000')

    def post(self, path, body=None, headers=None):
        return self.client.post('/auth/' + path, json=body or {}, headers=headers or HEADERS)

    def assert_private(self, response):
        self.assertEqual(response.headers['cache-control'], 'no-store')
        for text in ('access-one', 'refresh-one', CREDENTIALS['password'], 'synthetic-publishable-key'):
            self.assertNotIn(text, response.text)
        for name in ('access_token', 'refresh_token', 'password', 'user_metadata', 'app_metadata'):
            self.assertNotIn(name, response.text)

    def test_login_success(self):
        response = self.post('login', CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['authenticated'])
        self.assertEqual(self.client.cookies['bs_access'], 'access-one')
        self.assertEqual(self.client.cookies['bs_refresh'], 'refresh-one')
        self.assert_private(response)
        self.assertEqual(self.requests[-1].url.params['grant_type'], 'password')
        self.assertNotIn('authorization', self.requests[-1].headers)
        self.assertEqual(self.requests[-1].headers['apikey'], 'synthetic-publishable-key')
        for cookie in response.headers.get_list('set-cookie'):
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=lax', cookie)
            self.assertIn('Path=/', cookie)
            self.assertIn('Max-Age=', cookie)
            self.assertIn('expires=', cookie)

    def test_login_failure_is_generic(self):
        self.status, self.reply = 400, {'msg': 'sensitive upstream detail'}
        response = self.post('login', CREDENTIALS)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('sensitive', response.text)
        self.assertNotIn('set-cookie', response.headers)
        self.assert_private(response)

    def test_signup_requires_confirmation_without_session(self):
        self.reply = USER
        response = self.post('signup', CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'user': None, 'authenticated': False, 'confirmation_required': True})
        self.assertNotIn('bs_access=', response.headers.get('set-cookie', ''))
        self.assertIn('bs_pkce_', response.headers.get('set-cookie', ''))
        self.assert_private(response)

    def test_signup_with_session_and_existing_account_rejection(self):
        response = self.post('signup', CREDENTIALS)
        self.assertTrue(response.json()['authenticated'])
        self.status = 422
        response = self.post('signup', CREDENTIALS)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.cookies['bs_access'], 'access-one')
        self.assertNotIn('set-cookie', response.headers)

    def test_me_missing_invalid_and_valid(self):
        response = self.client.get('/auth/me')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.requests)
        self.client.cookies.set('bs_access', 'access-one')
        self.status = 401
        response = self.client.get('/auth/me')
        self.assertEqual(response.status_code, 401)
        self.assert_private(response)
        self.status, self.reply = 200, USER
        response = self.client.get('/auth/me')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'id': USER['id'], 'email': USER['email']})
        self.assertEqual(self.requests[-1].headers['authorization'], 'Bearer access-one')
        self.assertEqual(self.requests[-1].url.path, '/auth/v1/user')
        self.assert_private(response)

    def test_refresh_rotates_both_cookies(self):
        self.post('login', CREDENTIALS)
        self.reply = session(suffix='rotated')
        response = self.post('refresh')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.requests[-1].content), {'refresh_token': 'refresh-one'})
        self.assertEqual(self.requests[-1].url.params['grant_type'], 'refresh_token')
        self.assertEqual(self.client.cookies['bs_access'], 'access-rotated')
        self.assertEqual(self.client.cookies['bs_refresh'], 'refresh-rotated')
        self.assertNotIn('rotated', response.text)
        self.assert_private(response)

    def test_refresh_rejection_clears_cookies_and_outage_retains_them(self):
        self.post('login', CREDENTIALS)
        self.status = 503
        response = self.post('refresh')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.client.cookies['bs_refresh'], 'refresh-one')
        self.status = 400
        response = self.post('refresh')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(list(self.client.cookies))
        self.assert_private(response)

    def test_missing_refresh(self):
        response = self.post('refresh')
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.requests)

    def test_logout_revokes_current_session_and_deletes_cookies(self):
        self.post('login', CREDENTIALS)
        self.status = 204
        response = self.post('logout')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list(self.client.cookies))
        self.assertEqual(self.requests[-1].url.path, '/auth/v1/logout')
        self.assertEqual(self.requests[-1].url.params['scope'], 'local')
        self.assertEqual(self.requests[-1].headers['authorization'], 'Bearer access-one')
        for cookie in response.headers.get_list('set-cookie'):
            self.assertIn('Max-Age=0', cookie)
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=lax', cookie)
            self.assertIn('Path=/', cookie)
        self.assert_private(response)

    def test_logout_rejected_access_retries_with_refresh_before_revocation(self):
        self.client.cookies.set('bs_access', 'expired-access', domain='localhost.local', path='/')
        self.client.cookies.set('bs_refresh', 'refresh-one', domain='localhost.local', path='/')
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.path.endswith('/token'):
                return httpx.Response(200, json=session(suffix='renewed'))
            if request.headers.get('authorization') == 'Bearer expired-access':
                return httpx.Response(401, json={'msg': 'expired'})
            return httpx.Response(204)
        self.app.state.supabase_transport = httpx.MockTransport(handler)
        response = self.post('logout')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.url.path for r in calls],
                         ['/auth/v1/logout', '/auth/v1/token', '/auth/v1/logout'])
        self.assertEqual(calls[-1].headers['authorization'], 'Bearer access-renewed')
        self.assertFalse(list(self.client.cookies))

    def test_provider_rate_limits_and_invalid_signup_shape(self):
        self.status = 429
        response = self.post('login', CREDENTIALS)
        self.assertEqual(response.status_code, 429)
        self.assert_private(response)
        self.status, self.reply = 200, {}
        self.assertEqual(self.post('signup', CREDENTIALS).status_code, 503)

    def test_logout_missing_session_is_idempotent(self):
        self.assertEqual(self.post('logout').status_code, 200)
        self.assertFalse(self.requests)

    def test_logout_outage_clears_locally_without_claiming_revocation(self):
        self.post('login', CREDENTIALS)
        self.status = 503
        response = self.post('logout')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(list(self.client.cookies))
        self.assert_private(response)

    def test_logout_refreshes_when_access_cookie_expired(self):
        self.client.cookies.set('bs_refresh', 'refresh-one', domain='localhost.local', path='/')
        response = self.post('logout')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.url.path for r in self.requests], ['/auth/v1/token', '/auth/v1/logout'])
        self.assertEqual(self.requests[-1].headers['authorization'], 'Bearer access-one')

    def test_csrf_rejects_missing_origin_header_and_wrong_content_type(self):
        for path in ('signup', 'login', 'refresh', 'logout'):
            for headers in ({'Content-Type': 'application/json'},
                            {'Origin': ORIGIN, 'Content-Type': 'application/json'},
                            {**HEADERS, 'Origin': 'null'},
                            {**HEADERS, 'Origin': 'https://evil.example'},
                            {**HEADERS, 'Sec-Fetch-Site': 'cross-site'}):
                with self.subTest(path=path, headers=headers):
                    response = self.post(path, CREDENTIALS if path in {'login','signup'} else {}, headers)
                    self.assertEqual(response.status_code, 403)
                    self.assert_private(response)
        response = self.post('login', CREDENTIALS, {**HEADERS, 'Content-Type': 'text/plain'})
        self.assertEqual(response.status_code, 415)
        self.assertFalse(self.requests)

    def test_cors_allowed_and_disallowed_origins(self):
        response = self.client.options('/auth/login', headers={
            'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type,x-csrf-protection'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], ORIGIN)
        self.assertEqual(response.headers['access-control-allow-credentials'], 'true')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        for method in ('OPTIONS', 'GET'):
            response = self.client.request(method, '/auth/me', headers={
                'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'GET'})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('access-control-allow-origin', response.headers)

    def test_outages_timeouts_and_malformed_upstream(self):
        self.status = 502
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 503)
        def timeout(request):
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        self.app.state.supabase_transport = httpx.MockTransport(timeout)
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 503)
        self.app.state.supabase_transport = httpx.MockTransport(lambda r: httpx.Response(200, text='not json'))
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 503)
        self.app.state.supabase_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={'access_token':'bad'}))
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 503)

    def test_validation_never_echoes_input_or_accepts_roles(self):
        for body in ({**CREDENTIALS, 'role': 'admin'}, {**CREDENTIALS, 'email': 'invalid'},
                     {**CREDENTIALS, 'password': {'token': 'synthetic-secret'}}, {}):
            response = self.post('login', body)
            self.assertEqual(response.status_code, 422)
            self.assert_private(response)
            self.assertNotIn('synthetic-secret', response.text)
        self.assertFalse(self.requests)

    def test_unconfigured_service_is_503(self):
        self.app.state.auth_settings = AuthSettings(development=True, frontend_origins=(ORIGIN,))
        self.assertEqual(self.post('login', CREDENTIALS).status_code, 503)

    def test_production_cookies_and_deletion_attributes(self):
        app = make_app(lambda r: httpx.Response(200, json=session()), production=True)
        with TestClient(app, base_url='https://backend.example.com') as client:
            headers = {**HEADERS, 'Origin': 'https://frontend.example.com'}
            response = client.post('/auth/login', json=CREDENTIALS, headers=headers)
            for cookie in response.headers.get_list('set-cookie'):
                self.assertIn('__Host-', cookie)
                self.assertIn('Secure', cookie)
                self.assertNotIn('Domain=', cookie)
            self.assertTrue(client.cookies.get('__Host-bs_access'))
            response = client.post('/auth/logout', json={}, headers=headers)
            for cookie in response.headers.get_list('set-cookie'):
                self.assertIn('Secure', cookie)
                self.assertIn('Max-Age=0', cookie)
            self.assertFalse(list(client.cookies))

    def test_auth_openapi(self):
        schema = self.client.get('/openapi.json').json()
        expected = {'/auth/signup':'post', '/auth/login':'post', '/auth/me':'get',
                    '/auth/refresh':'post', '/auth/logout':'post', '/auth/callback/{purpose}/{transaction_id}':'get', '/auth/recovery':'get',
                    '/auth/password/reset-request':'post', '/auth/password/update':'post'}
        self.assertEqual(set(schema['paths']), set(expected))
        for path, method in expected.items():
            operation = schema['paths'][path][method]
            self.assertEqual(operation['tags'], ['Authentication'])
            if path.startswith('/auth/callback/'):
                self.assertIn('303', operation['responses'])
            else:
                self.assertIn('schema', operation['responses']['200']['content']['application/json'])
        self.assertEqual(self.client.get('/docs').status_code, 200)


class ConcurrentSessions(unittest.IsolatedAsyncioTestCase):
    async def test_two_users_remain_isolated_during_login_refresh_and_me(self):
        async def handler(request):
            await asyncio.sleep(0.01)
            self.assertNotIn('cookie', request.headers)
            if request.url.path.endswith('/user'):
                user = USER2 if request.headers['authorization'] == 'Bearer access-two' else USER
                return httpx.Response(200, json=user)
            body = json.loads(request.content)
            two = body.get('email') == 'two@example.com' or body.get('refresh_token') == 'refresh-two'
            return httpx.Response(200, json=session(USER2 if two else USER, 'two' if two else 'one'))
        app = make_app(handler)
        async def flow(email):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8000') as client:
                response = await client.post('/auth/login', json={**CREDENTIALS, 'email':email}, headers=HEADERS)
                self.assertEqual(response.status_code, 200)
                response = await client.post('/auth/refresh', json={}, headers=HEADERS)
                self.assertEqual(response.status_code, 200)
                return (await client.get('/auth/me')).json()
        first, second = await asyncio.gather(flow('one@example.com'), flow('two@example.com'))
        self.assertEqual(first['id'], USER['id'])
        self.assertEqual(second['id'], USER2['id'])


class ConfigurationTests(unittest.TestCase):
    def test_unsafe_origins_and_cookie_settings_rejected(self):
        for kwargs in ({'frontend_origins':('*',)}, {'frontend_origins':('http://example.com',)},
                       {'frontend_origins':('https://example.com/path',)},
                       {'development':True, 'same_site':'none'}, {'supabase_url':'http://example.com'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AuthSettings(**kwargs)
