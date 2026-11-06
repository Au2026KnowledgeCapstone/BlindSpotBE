"""End-to-end feature dependencies with Supabase verification mocked over HTTP."""
import json
from pathlib import Path
import re
import unittest
from uuid import UUID

from backend.feature_security import feature_user
from backend.main import app
from feature_test_support import feature_client, CSRF, ORIGIN, USER_A, USER_B

CONTRACTS = json.loads(Path(__file__).with_name('route_contracts.json').read_text())
FEATURES = [c for c in CONTRACTS if c['path'] != '/' and not c['path'].startswith('/internal/')]
INTERNAL = [c for c in CONTRACTS if c['path'].startswith('/internal/')]


def concrete(path):
    return re.sub(r'{(\w+)}', r'sample-\1', path)


class FeatureSessionSecurity(unittest.TestCase):
    def setUp(self):
        self.context = feature_client()
        self.client, self.calls, self.states = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def login_cookie(self, token='user-a'):
        self.client.cookies.set('bs_access', token, domain='localhost.local', path='/')

    def test_all_33_feature_operations_require_real_verification(self):
        self.assertEqual(len(FEATURES), 33)
        for token in (None, 'invalid.jwt.with.unverified.claims'):
            self.client.cookies.clear()
            if token:
                self.login_cookie(token)
            for contract in FEATURES:
                with self.subTest(token_present=bool(token), method=contract['method'], path=contract['path']):
                    response = self.client.request(contract['method'], concrete(contract['path']), json={}, headers=CSRF)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(len(self.calls), 33)
        self.assertTrue(all(r.url.path == '/auth/v1/user' for r in self.calls))

    def test_anonymous_mutations_return_401_even_without_csrf_or_json(self):
        for contract in FEATURES:
            if contract['method'] in {'POST','PATCH'}:
                with self.subTest(path=contract['path']):
                    self.assertEqual(self.client.request(contract['method'], concrete(contract['path'])).status_code, 401)

    def test_valid_users_reach_all_intended_handlers_without_implementing_services(self):
        self.login_cookie()
        for contract in FEATURES:
            with self.subTest(path=contract['path'], method=contract['method']):
                response = self.client.request(contract['method'], concrete(contract['path']),
                                               json={'text':'hello','nested':[1,True,None]}, headers=CSRF)
                self.assertEqual(response.status_code, contract['status'])
                self.assertEqual(response.json(), contract['body'])
                self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(len(self.calls), 33)
        self.assertTrue(all(state['current_user'].id == UUID(USER_A['id']) for state in self.states))

    def test_every_feature_mutation_rejects_csrf_independently_of_cors(self):
        self.login_cookie()
        variants = (
            {'Content-Type':'application/json'},
            {'Origin':ORIGIN,'Content-Type':'application/json'},
            {**CSRF,'Origin':'https://evil.example'},
            {**CSRF,'Origin':'null'},
            {**CSRF,'X-CSRF-Protection':'wrong'},
            {**CSRF,'Sec-Fetch-Site':'cross-site'},
        )
        for contract in FEATURES:
            if contract['method'] not in {'POST','PATCH'}:
                continue
            for headers in variants:
                with self.subTest(path=contract['path'], headers=headers):
                    response = self.client.request(contract['method'], concrete(contract['path']), json={}, headers=headers)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn('feature_session_verified', self.states[-1])
            response = self.client.request(contract['method'], concrete(contract['path']), content='{}',
                                           headers={**CSRF,'Content-Type':'text/plain'})
            self.assertEqual(response.status_code, 415)

    def test_generated_head_routes_cannot_bypass_feature_dependencies(self):
        for token in (None, 'invalid', 'user-a'):
            self.client.cookies.clear()
            if token:
                self.login_cookie(token)
            for contract in FEATURES:
                if contract['method'] == 'GET':
                    with self.subTest(path=contract['path'], token=token):
                        response = self.client.head(concrete(contract['path']))
                        self.assertEqual(response.status_code, contract['status'] if token == 'user-a' else 401)
                        self.assertEqual(response.content, b'')

    def test_identity_comes_from_supabase_not_body_queries_or_metadata(self):
        for token, expected in [('user-a',USER_A),('user-b',USER_B)]:
            self.client.cookies.clear()
            self.login_cookie(token)
            response = self.client.post('/create-project?user_id=another&role=admin', headers=CSRF,
                                        json={'user_id':'forged','role':'admin'})
            self.assertEqual(response.status_code, 201)
            verified = self.states[-1]['current_user']
            self.assertEqual(str(verified.id), expected['id'])
            self.assertEqual(verified.email, expected['email'])
            self.assertFalse(hasattr(verified, 'role'))
            self.assertFalse(hasattr(verified, 'user_metadata'))

    def test_client_identity_headers_and_bearer_header_do_not_replace_cookie_session(self):
        response = self.client.get('/projects', headers={
            'X-User-Id': USER_A['id'], 'X-Role':'admin', 'Authorization':'Bearer user-a',
        })
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.calls)

    def test_verification_outage_is_not_an_invalid_session(self):
        self.login_cookie('outage')
        self.assertEqual(self.client.get('/projects').status_code, 503)
        self.assertNotIn('current_user', self.states[-1])

    def test_health_docs_options_and_auth_entry_points_remain_public(self):
        for path in ('/','/docs','/openapi.json'):
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.options('/projects').status_code, 200)
        self.assertFalse(self.calls)
        # Auth endpoints retain their own CSRF policy, not feature authentication.
        for path in ('/auth/login','/auth/signup','/auth/password/reset-request'):
            self.assertEqual(self.client.post(path,json={}).status_code, 403)
        callback = self.client.get('/auth/callback/signup/'+'x'*32, params={'code':'synthetic-code'})
        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers['location'], 'http://localhost:3000/login')
        self.assertFalse(self.calls)

    def test_internal_callbacks_remain_nonfunctional_without_user_authentication(self):
        for token in (None, 'user-a'):
            self.client.cookies.clear()
            if token:
                self.login_cookie(token)
            for contract in INTERNAL:
                response = self.client.post(concrete(contract['path']), json={'untrusted':'worker-event'})
                self.assertEqual(response.status_code, 501)
                self.assertEqual(response.json(), contract['body'])
        self.assertFalse(self.calls)

    def test_dependency_coverage_including_head_is_explicit(self):
        for route in app.routes:
            path = getattr(route,'path','')
            if path and path != '/' and not path.startswith(('/auth/','/internal/')) and path not in {
                '/docs','/redoc','/openapi.json','/docs/oauth2-redirect'}:
                with self.subTest(path=path, methods=route.methods):
                    self.assertIn(feature_user, [d.dependency for d in route.dependencies])
