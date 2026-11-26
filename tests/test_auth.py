"""Only synthetic credentials and mocked HTTP responses; never contact Supabase.

Ported from feat/backend-auth (tests/test_auth.py) onto main.app — the
routes under test now live on the single production app (every route lives
in main.py), not a fresh FastAPI() + router per test. Most tests reuse
main.app and override app.state.auth_settings / app.state.supabase_transport
per test; both are read fresh per request, so this is safe. The CORS
middleware and auth_response_security bind their settings once, at
app-construction time — the handful of tests that need a different
trusted-origins list reload the main module with patched env vars instead.

Email callback and recovery tests exercise the same app and mocked transport.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import os
import time
import unittest
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

import main
from app.core import auth_pkce
from app.core.auth_config import AuthSettings
from app.core.observability import clean_text

ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1", "Content-Type": "application/json"}
USER = {
    "id": "11111111-1111-4111-8111-111111111111",
    "email": "one@example.com",
    "user_metadata": {"role": "admin"},
    "app_metadata": {"irrelevant": True},
}
USER2 = {"id": "22222222-2222-4222-8222-222222222222", "email": "two@example.com"}
CREDENTIALS = {"email": "one@example.com", "password": "Synthetic-pass-1!"}


def session(user=USER, suffix="one"):
    return {
        "access_token": f"access-{suffix}",
        "refresh_token": f"refresh-{suffix}",
        "expires_in": 3600,
        "user": user,
    }


def make_settings(*, production=False):
    return AuthSettings(
        supabase_url="https://example.supabase.co",
        publishable_key="synthetic-publishable-key",
        flow_encryption_key=base64.urlsafe_b64encode(b"k" * 32).decode(),
        development=not production,
        frontend_origins=("https://frontend.example.com",) if production else (ORIGIN,),
        backend_origin="https://backend.example.com" if production else "http://localhost:8000",
    )


def make_app(handler, *, production=False):
    main.app.state.auth_settings = make_settings(production=production)
    main.app.state.supabase_transport = httpx.MockTransport(handler)
    return main.app


@contextmanager
def reloaded_app(env: dict):
    """CORS and auth_response_security bind their origins at registration
    time, not per-request. These few tests need a fresh main module with
    different env vars, not just a fresh app.state.auth_settings."""
    previous = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    try:
        yield importlib.reload(main)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(main)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.reply = session()
        self.status = 200

        def handler(request):
            self.requests.append(request)
            return httpx.Response(self.status, json=self.reply) if self.status != 204 else httpx.Response(204)

        self.app = make_app(handler)
        self.client = TestClient(self.app, base_url="http://localhost:8000")

    def post(self, path, body=None, headers=None):
        return self.client.post("/auth/" + path, json=body or {}, headers=headers or HEADERS)

    def assert_private(self, response):
        self.assertEqual(response.headers["cache-control"], "no-store")
        for text in ("access-one", "refresh-one", CREDENTIALS["password"], "synthetic-publishable-key"):
            self.assertNotIn(text, response.text)
        for name in ("access_token", "refresh_token", "password", "user_metadata", "app_metadata"):
            self.assertNotIn(name, response.text)

    def test_login_success(self):
        response = self.post("login", CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["authenticated"])
        self.assertEqual(self.client.cookies["bs_access"], "access-one")
        self.assertEqual(self.client.cookies["bs_refresh"], "refresh-one")
        self.assert_private(response)
        self.assertEqual(self.requests[-1].url.params["grant_type"], "password")
        self.assertNotIn("authorization", self.requests[-1].headers)
        self.assertEqual(self.requests[-1].headers["apikey"], "synthetic-publishable-key")
        for cookie in response.headers.get_list("set-cookie"):
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=lax", cookie)
            self.assertIn("Path=/", cookie)
            self.assertIn("Max-Age=", cookie)
            self.assertIn("expires=", cookie)

    def test_login_failure_is_generic(self):
        self.status, self.reply = 400, {"msg": "sensitive upstream detail"}
        response = self.post("login", CREDENTIALS)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("sensitive", response.text)
        self.assertNotIn("set-cookie", response.headers)
        self.assert_private(response)

    def test_signup_requires_confirmation_without_session(self):
        self.reply = USER
        response = self.post("signup", CREDENTIALS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user": None, "authenticated": False, "confirmation_required": True})
        self.assertNotIn("bs_access=", response.headers.get("set-cookie", ""))
        self.assertIn("bs_pkce_", response.headers.get("set-cookie", ""))
        self.assert_private(response)

    def test_signup_with_immediate_session(self):
        response = self.post("signup", CREDENTIALS)
        self.assertEqual(response.json(), {
            "user": {"id": USER["id"], "email": USER["email"]},
            "authenticated": True, "confirmation_required": False,
        })
        self.assertEqual(self.client.cookies["bs_access"], "access-one")
        self.assert_private(response)

    def test_pending_signup_has_identical_public_outcomes_for_new_and_existing_accounts(self):
        self.client.cookies.set("bs_access", "existing-session")
        outcomes = [
            (200, USER),  # New or previously unconfirmed account.
            (200, {**USER2, "identities": []}),  # Obfuscated confirmed account.
            (422, {"error_code": "user_already_exists", "msg": "private detail"}),
            (400, {"error_code": "email_exists"}),
            (422, {"msg": "User already registered"}),
            (429, {"error_code": "over_email_send_rate_limit"}),  # Account-specific send cooldown.
        ]
        for self.status, self.reply in outcomes:
            with self.subTest(status=self.status):
                response = self.post("signup", CREDENTIALS)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {
                    "user": None, "authenticated": False, "confirmation_required": True,
                })
                cookies = response.headers.get_list("set-cookie")
                self.assertEqual(len(cookies), 1)
                self.assertRegex(cookies[0], r"^bs_pkce_[\w-]+=.+; HttpOnly; Max-Age=900; Path=/; SameSite=lax$")
                self.assertEqual(self.client.cookies["bs_access"], "existing-session")
                self.assert_private(response)

    def test_signup_keeps_safe_invalid_input_rate_limit_and_outage_errors(self):
        response = self.post("signup", {**CREDENTIALS, "password": "short"})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.requests)
        for self.status, expected in [(422, 400), (429, 429), (500, 503)]:
            with self.subTest(status=self.status):
                self.reply = {"error_code": "weak_password", "msg": "private provider detail"}
                response = self.post("signup", CREDENTIALS)
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("private provider detail", response.text)
                self.assertNotIn("set-cookie", response.headers)
                self.assert_private(response)
        self.status, self.reply = 200, {**USER, "refresh_token": "partial"}
        self.assertEqual(self.post("signup", CREDENTIALS).status_code, 503)

    def test_resend_is_private_and_reuses_signup_callback_with_fresh_pkce(self):
        path = "confirmation/resend"
        payload = {"email": CREDENTIALS["email"]}
        outcomes = [
            (200, {}),  # Missing or confirmed address.
            (429, {"error_code": "over_email_send_rate_limit"}),
            (500, {"msg": "private delivery error"}),
            (200, {"message_id": "private provider detail"}),  # Eligible address.
        ]
        redirects = set()
        challenges = set()
        for self.status, self.reply in outcomes:
            response = self.post(path, payload)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "message": "If confirmation is still needed, check your email for a link.",
            })
            self.assertEqual(len(response.headers.get_list("set-cookie")), 1)
            self.assertIn("bs_pkce_", response.headers["set-cookie"])
            self.assert_private(response)
            request = self.requests[-1]
            self.assertEqual(request.url.path, "/auth/v1/resend")
            body = json.loads(request.content)
            challenge = body.pop("code_challenge")
            self.assertEqual(body, {"type": "signup", **payload, "code_challenge_method": "s256"})
            callback = request.url.params["redirect_to"]
            callback_id = callback.rsplit("/", 1)[-1]
            self.assertIn(f"bs_pkce_{callback_id}=", response.headers["set-cookie"])
            self.assertTrue(callback.startswith("http://localhost:8000/auth/callback/signup/"))
            redirects.add(callback)
            challenges.add(challenge)
        self.assertEqual(len(redirects), len(outcomes))
        self.assertEqual(len(challenges), len(outcomes))
        other_browser = TestClient(self.app, base_url="http://localhost:8000")
        response = other_browser.get(callback, params={"code": "synthetic-code"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("bs_access", other_browser.cookies)
        self.assertEqual(len(self.requests), len(outcomes))

        self.status, self.reply = 200, session()
        response = self.client.get(callback, params={"code": "synthetic-code"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], ORIGIN + "/login?confirmation=confirmed")
        self.assertEqual(self.client.cookies["bs_access"], "access-one")
        self.assertNotIn(f"bs_pkce_{callback_id}", self.client.cookies)
        exchange = self.requests[-1]
        self.assertEqual(exchange.url.params["grant_type"], "pkce")
        exchange_body = json.loads(exchange.content)
        self.assertEqual(exchange_body["auth_code"], "synthetic-code")
        digest = hashlib.sha256(exchange_body["code_verifier"].encode()).digest()
        self.assertEqual(base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), challenge)

    def start_email_flow(self, purpose):
        self.status, self.reply = 200, USER
        path, body = ("signup", CREDENTIALS) if purpose == "signup" else (
            "password/reset-request", {"email": USER["email"]},
        )
        self.assertEqual(self.post(path, body).status_code, 200)
        return self.requests[-1].url.params["redirect_to"]

    def test_confirmation_callback_redirects_with_only_a_fixed_outcome(self):
        for status, payload, params, outcome in (
            (400, {"error_code": "flow_state_expired"}, {"code": "private-code"}, "expired"),
            (503, {"msg": "private provider text"}, {"code": "private-code"}, "failed"),
            (200, {}, {"error_code": "otp_expired", "error_description": "private provider text"}, "expired"),
            (200, {}, {"code": ["one", "two"]}, "invalid"),
        ):
            with self.subTest(outcome=outcome):
                callback = self.start_email_flow("signup")
                self.status, self.reply = status, payload
                response = self.client.get(callback, params=params, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], ORIGIN + "/login?confirmation=" + outcome)
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertNotIn("private", response.text)
                self.assertNotIn("bs_access", self.client.cookies)
                self.assertNotIn("bs_pkce_" + callback.rsplit("/", 1)[-1], self.client.cookies)

    def test_confirmation_preserves_an_existing_workspace_session(self):
        self.post("login", CREDENTIALS)
        callback = self.start_email_flow("signup")
        self.reply = session(user=USER2, suffix="different")
        response = self.client.get(callback, params={"code": "synthetic-code"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], ORIGIN + "/login?confirmation=confirmed")
        self.assertEqual(self.client.cookies["bs_access"], "access-one")
        self.assertEqual(self.client.cookies["bs_refresh"], "refresh-one")

    def test_confirmation_reports_an_expired_browser_transaction_without_exchange(self):
        callback = self.start_email_flow("signup")
        identifier = callback.rsplit("/", 1)[-1]
        name = "bs_pkce_" + identifier
        settings = self.app.state.auth_settings
        pending = auth_pkce.unseal(settings, self.client.cookies[name].strip('"'))
        self.client.cookies.clear()
        self.client.cookies.set(name, auth_pkce.seal(settings, {**pending, "exp": int(time.time()) - 1}))
        response = self.client.get(callback, params={"code": "synthetic-code"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], ORIGIN + "/login?confirmation=expired")
        self.assertEqual(len(self.requests), 1)

    def test_auth_callback_paths_and_queries_are_redacted_in_structured_logs(self):
        for target in (
            "/auth/callback/signup/private-id?code=private-code",
            "/auth/v1/signup?redirect_to=https%3A%2F%2Fhost%2Fauth%2Fcallback%2Fsignup%2Fprivate-id",
        ):
            logged = clean_text(target)
            self.assertNotIn("private", logged)
            self.assertIn("/auth/callback/[redacted]", logged)

    def test_reset_request_masks_per_address_outcomes_but_surfaces_request_throttling(self):
        for self.status, self.reply in (
            (200, {}), (400, {"msg": "private account detail"}),
            (429, {"error_code": "over_email_send_rate_limit"}), (500, {"msg": "private SMTP detail"}),
        ):
            response = self.post("password/reset-request", {"email": USER["email"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "message": "If this address is eligible for password reset, check your email for a link.",
            })
            self.assertIn("bs_pkce_", response.headers["set-cookie"])
        self.status, self.reply = 429, {"error_code": "over_request_rate_limit"}
        response = self.post("password/reset-request", {"email": USER["email"]})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("set-cookie", response.headers)

    def issue_recovery(self):
        callback = self.start_email_flow("recovery")
        self.reply = session(suffix="recovery")
        response = self.client.get(callback, params={"code": "synthetic-reset"}, follow_redirects=False)
        self.assertEqual(response.headers["location"], ORIGIN + "/reset-password")
        self.assertIn("bs_recovery=", response.headers["set-cookie"])
        self.assertIn("HttpOnly; Max-Age=600", response.headers["set-cookie"])
        self.assertNotIn("access-recovery", response.headers["set-cookie"])
        self.assertNotIn("refresh-recovery", response.headers["set-cookie"])

    def test_recovery_credentials_only_authorize_password_reset(self):
        self.issue_recovery()
        self.assertNotIn("bs_access", self.client.cookies)
        self.assertNotIn("bs_refresh", self.client.cookies)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/projects").status_code, 401)
        self.assertEqual(self.post("refresh").status_code, 401)
        self.assertIn("bs_recovery", self.client.cookies)
        self.reply = USER
        self.assertEqual(self.client.get("/auth/recovery").status_code, 200)
        self.assertEqual(self.post("password/update", {
            "user_id": USER2["id"], "password": "Synthetic-new-pass-2!",
        }).status_code, 401)
        self.assertEqual(self.requests[-1].method, "GET")
        response = self.post("password/update", {
            "user_id": USER["id"], "password": "Synthetic-new-pass-2!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("bs_recovery", self.client.cookies)
        self.assertEqual([req.method for req in self.requests[-3:]], ["GET", "PUT", "POST"])
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer access-recovery")
        self.assertEqual(self.client.get("/auth/recovery").status_code, 401)

    def test_expired_recovery_rejects_a_stale_update_before_contacting_provider(self):
        self.issue_recovery()
        settings = self.app.state.auth_settings
        grant = auth_pkce.unseal(settings, self.client.cookies["bs_recovery"].strip('"'))
        self.client.cookies.clear()
        self.client.cookies.set("bs_recovery", auth_pkce.seal(settings, {**grant, "exp": int(time.time()) - 1}))
        response = self.post("password/update", {"user_id": USER["id"], "password": "Synthetic-new-pass-2!"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.requests), 2)

    def test_logout_revokes_recovery_and_workspace_credentials(self):
        self.post("login", CREDENTIALS)
        self.issue_recovery()
        response = self.post("logout")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list(self.client.cookies))
        self.assertEqual(
            [r.headers["authorization"] for r in self.requests[-2:]],
            ["Bearer access-one", "Bearer access-recovery"],
        )

    def test_resend_enforces_csrf_validation_and_rate_limits(self):
        path = "confirmation/resend"
        payload = {"email": CREDENTIALS["email"]}
        self.assertEqual(self.post(path, payload, {"Origin": ORIGIN}).status_code, 403)
        self.assertEqual(self.post(path, payload, {**HEADERS, "Origin": "https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.post(path, {"email": "invalid"}).status_code, 422)
        self.assertFalse(self.requests)

        self.status, self.reply = 429, {"error_code": "over_request_rate_limit"}
        self.assertEqual(self.post(path, payload).status_code, 429)
        self.status, self.reply = 200, {}
        for _ in range(8):
            self.assertEqual(self.post(path, payload).status_code, 200)
        self.assertEqual(self.post(path, payload).status_code, 429)
        self.assertEqual(len(self.requests), 9)

    def test_email_request_transport_failures_are_safe(self):
        def offline(request):
            raise httpx.ConnectError("private transport detail", request=request)

        self.app.state.supabase_transport = httpx.MockTransport(offline)
        email = {"email": CREDENTIALS["email"]}
        for path, payload in [("signup", CREDENTIALS), ("confirmation/resend", email), ("password/reset-request", email)]:
            response = self.post(path, payload)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private transport detail", response.text)
            self.assertNotIn("set-cookie", response.headers)
            self.assert_private(response)

    def test_me_missing_invalid_and_valid(self):
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "session_missing")
        self.assertFalse(self.requests)
        self.client.cookies.set("bs_refresh", "refresh-one")
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")
        self.assertFalse(self.requests)
        self.client.cookies.set("bs_access", "access-one")
        self.status = 401
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assert_private(response)
        self.status, self.reply = 200, USER
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": USER["id"], "email": USER["email"]})
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer access-one")
        self.assertEqual(self.requests[-1].url.path, "/auth/v1/user")
        self.assert_private(response)

    def test_refresh_rotates_both_cookies(self):
        self.post("login", CREDENTIALS)
        self.reply = session(suffix="rotated")
        response = self.post("refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(self.requests[-1].content), {"refresh_token": "refresh-one"})
        self.assertEqual(self.requests[-1].url.params["grant_type"], "refresh_token")
        self.assertEqual(self.client.cookies["bs_access"], "access-rotated")
        self.assertEqual(self.client.cookies["bs_refresh"], "refresh-rotated")
        self.assertNotIn("rotated", response.text)
        self.assert_private(response)

    def test_refresh_temporary_rejections_retain_cookies(self):
        self.post("login", CREDENTIALS)
        cases = [
            (503, {}, 503), (429, {}, 429), (401, {}, 503), (403, {"error_code": "no_authorization"}, 503),
            (400, {"error_code": "validation_failed"}, 503), (409, {"error_code": "conflict"}, 503),
            (200, {"access_token": "incomplete"}, 503),
        ]
        for self.status, self.reply, expected in cases:
            with self.subTest(status=self.status, reply=self.reply):
                response = self.post("refresh")
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("set-cookie", response.headers)
                self.assertEqual(self.client.cookies["bs_refresh"], "refresh-one")
                self.assertEqual(self.client.cookies["bs_access"], "access-one")
                self.assert_private(response)

        def offline(request):
            raise httpx.ConnectError("private transport detail", request=request)

        self.app.state.supabase_transport = httpx.MockTransport(offline)
        response = self.post("refresh")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(self.client.cookies["bs_refresh"], "refresh-one")

    def test_refresh_definitive_rejection_clears_cookies(self):
        for code in ("refresh_token_not_found", "refresh_token_already_used", "session_expired", "session_not_found"):
            with self.subTest(code=code):
                self.status, self.reply = 200, session()
                self.post("login", CREDENTIALS)
                self.status, self.reply = 400, {"error_code": code, "msg": "private rejection"}
                response = self.post("refresh")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"]["code"], "session_invalid")
                self.assertFalse(list(self.client.cookies))
                self.assertNotIn(code, response.text)
                self.assertNotIn("private rejection", response.text)
                self.assert_private(response)

    def test_missing_refresh(self):
        response = self.post("refresh")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "session_invalid")
        self.assertFalse(self.requests)

    def test_logout_revokes_current_session_and_deletes_cookies(self):
        self.post("login", CREDENTIALS)
        self.status = 204
        response = self.post("logout")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list(self.client.cookies))
        self.assertEqual(self.requests[-1].url.path, "/auth/v1/logout")
        self.assertEqual(self.requests[-1].url.params["scope"], "local")
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer access-one")
        for cookie in response.headers.get_list("set-cookie"):
            self.assertIn("Max-Age=0", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=lax", cookie)
            self.assertIn("Path=/", cookie)
        self.assert_private(response)

    def test_logout_rejected_access_retries_with_refresh_before_revocation(self):
        self.client.cookies.set("bs_access", "expired-access", domain="localhost.local", path="/")
        self.client.cookies.set("bs_refresh", "refresh-one", domain="localhost.local", path="/")
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json=session(suffix="renewed"))
            if request.headers.get("authorization") == "Bearer expired-access":
                return httpx.Response(401, json={"msg": "expired"})
            return httpx.Response(204)

        self.app.state.supabase_transport = httpx.MockTransport(handler)
        response = self.post("logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.url.path for r in calls], ["/auth/v1/logout", "/auth/v1/token", "/auth/v1/logout"])
        self.assertEqual(calls[-1].headers["authorization"], "Bearer access-renewed")
        self.assertFalse(list(self.client.cookies))

    def test_provider_rate_limits_and_invalid_signup_shape(self):
        self.status = 429
        response = self.post("login", CREDENTIALS)
        self.assertEqual(response.status_code, 429)
        self.assert_private(response)
        self.status, self.reply = 200, {}
        self.assertEqual(self.post("signup", CREDENTIALS).status_code, 503)

    def test_logout_missing_session_is_idempotent(self):
        self.assertEqual(self.post("logout").status_code, 200)
        self.assertFalse(self.requests)

    def test_logout_outage_clears_locally_without_claiming_revocation(self):
        self.post("login", CREDENTIALS)
        self.status = 503
        response = self.post("logout")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(list(self.client.cookies))
        self.assert_private(response)

    def test_logout_refreshes_when_access_cookie_expired(self):
        self.client.cookies.set("bs_refresh", "refresh-one", domain="localhost.local", path="/")
        response = self.post("logout")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r.url.path for r in self.requests], ["/auth/v1/token", "/auth/v1/logout"])
        self.assertEqual(self.requests[-1].headers["authorization"], "Bearer access-one")

    def test_csrf_rejects_missing_origin_header_and_wrong_content_type(self):
        for path in ("signup", "login", "refresh", "logout"):
            for headers in (
                {"Content-Type": "application/json"},
                {"Origin": ORIGIN, "Content-Type": "application/json"},
                {**HEADERS, "Origin": "null"},
                {**HEADERS, "Origin": "https://evil.example"},
                {**HEADERS, "Sec-Fetch-Site": "cross-site"},
            ):
                with self.subTest(path=path, headers=headers):
                    response = self.post(path, CREDENTIALS if path in {"login", "signup"} else {}, headers)
                    self.assertEqual(response.status_code, 403)
                    self.assert_private(response)
        response = self.post("login", CREDENTIALS, {**HEADERS, "Content-Type": "text/plain"})
        self.assertEqual(response.status_code, 415)
        self.assertFalse(self.requests)

    def test_outages_timeouts_and_malformed_upstream(self):
        self.status = 502
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 503)

        def timeout(request):
            raise httpx.ReadTimeout("synthetic timeout", request=request)

        self.app.state.supabase_transport = httpx.MockTransport(timeout)
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 503)
        self.app.state.supabase_transport = httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 503)
        self.app.state.supabase_transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"access_token": "bad"})
        )
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 503)

    def test_validation_never_echoes_input_or_accepts_roles(self):
        for body in (
            {**CREDENTIALS, "role": "admin"},
            {**CREDENTIALS, "email": "invalid"},
            {**CREDENTIALS, "password": {"token": "synthetic-secret"}},
            {},
        ):
            response = self.post("login", body)
            self.assertEqual(response.status_code, 422)
            self.assert_private(response)
            self.assertNotIn("synthetic-secret", response.text)
        self.assertFalse(self.requests)

    def test_unconfigured_service_is_503(self):
        self.app.state.auth_settings = AuthSettings(development=True, frontend_origins=(ORIGIN,))
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 503)

    def test_auth_openapi(self):
        schema = self.client.get("/openapi.json").json()
        expected = {
            "/auth/signup": "post", "/auth/login": "post", "/auth/me": "get",
            "/auth/confirmation/resend": "post",
            "/auth/refresh": "post", "/auth/logout": "post",
            "/auth/callback/{purpose}/{transaction_id}": "get", "/auth/recovery": "get",
            "/auth/password/reset-request": "post", "/auth/password/update": "post",
        }
        self.assertEqual(set(expected) <= set(schema["paths"]), True)
        for path, method in expected.items():
            operation = schema["paths"][path][method]
            self.assertEqual(operation["tags"], ["Auth"])
            if path.startswith("/auth/callback/"):
                self.assertIn("303", operation["responses"])
            else:
                self.assertIn("schema", operation["responses"]["200"]["content"]["application/json"])
        self.assertEqual(self.client.get("/docs").status_code, 200)


class CORSAndProductionTests(unittest.TestCase):
    """These three need a differently-configured app (CORS/cookie settings
    bind at registration time, not per-request), so they reload main with
    patched env vars rather than reusing the shared singleton."""

    def test_cors_allowed_and_disallowed_origins(self):
        with reloaded_app(
            {"APP_ENV": "development", "AUTH_FRONTEND_ORIGINS": ORIGIN, "AUTH_BACKEND_ORIGIN": "http://localhost:8000"}
        ) as reloaded:
            client = TestClient(reloaded.app, base_url="http://localhost:8000")
            response = client.options(
                "/auth/login",
                headers={
                    "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-csrf-protection",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
            self.assertEqual(response.headers["access-control-allow-credentials"], "true")
            for method in ("OPTIONS", "GET"):
                response = client.request(
                    method, "/auth/me",
                    headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
                )
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_production_cookies_and_deletion_attributes(self):
        with reloaded_app(
            {
                "APP_ENV": "production",
                "AUTH_FRONTEND_ORIGINS": "https://frontend.example.com",
                "AUTH_BACKEND_ORIGIN": "https://backend.example.com",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "synthetic-publishable-key",
            }
        ) as reloaded:
            reloaded.app.state.supabase_transport = httpx.MockTransport(
                lambda r: httpx.Response(200, json=session())
            )
            with TestClient(reloaded.app, base_url="https://backend.example.com") as client:
                headers = {**HEADERS, "Origin": "https://frontend.example.com"}
                response = client.post("/auth/login", json=CREDENTIALS, headers=headers)
                for cookie in response.headers.get_list("set-cookie"):
                    self.assertIn("__Host-", cookie)
                    self.assertIn("Secure", cookie)
                    self.assertNotIn("Domain=", cookie)
                self.assertTrue(client.cookies.get("__Host-bs_access"))
                response = client.post("/auth/logout", json={}, headers=headers)
                for cookie in response.headers.get_list("set-cookie"):
                    self.assertIn("Secure", cookie)
                    self.assertIn("Max-Age=0", cookie)
                self.assertFalse(list(client.cookies))


class ConcurrentSessions(unittest.IsolatedAsyncioTestCase):
    async def test_two_users_remain_isolated_during_login_refresh_and_me(self):
        async def handler(request):
            await asyncio.sleep(0.01)
            self.assertNotIn("cookie", request.headers)
            if request.url.path.endswith("/user"):
                user = USER2 if request.headers["authorization"] == "Bearer access-two" else USER
                return httpx.Response(200, json=user)
            body = json.loads(request.content)
            two = body.get("email") == "two@example.com" or body.get("refresh_token") == "refresh-two"
            return httpx.Response(200, json=session(USER2 if two else USER, "two" if two else "one"))

        app = make_app(handler)

        async def flow(email):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
            ) as client:
                response = await client.post("/auth/login", json={**CREDENTIALS, "email": email}, headers=HEADERS)
                self.assertEqual(response.status_code, 200)
                response = await client.post("/auth/refresh", json={}, headers=HEADERS)
                self.assertEqual(response.status_code, 200)
                return (await client.get("/auth/me")).json()

        first, second = await asyncio.gather(flow("one@example.com"), flow("two@example.com"))
        self.assertEqual(first["id"], USER["id"])
        self.assertEqual(second["id"], USER2["id"])


class ConfigurationTests(unittest.TestCase):
    def test_unsafe_origins_and_cookie_settings_rejected(self):
        for kwargs in (
            {"frontend_origins": ("*",)},
            {"frontend_origins": ("http://example.com",)},
            {"frontend_origins": ("https://example.com/path",)},
            {"development": True, "same_site": "none"},
            {"supabase_url": "http://example.com"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AuthSettings(**kwargs)
