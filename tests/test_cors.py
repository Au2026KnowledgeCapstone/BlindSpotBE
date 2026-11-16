import unittest

from backend.main import app


ORIGIN = "https://blindspotfe-158196513287.europe-west1.run.app"


class FrontendCorsTests(unittest.TestCase):
    def setUp(self):
        self.previous_origins = app.config["CORS_ALLOWED_ORIGINS"]
        app.config["CORS_ALLOWED_ORIGINS"] = {ORIGIN}
        self.client = app.test_client()

    def tearDown(self):
        app.config["CORS_ALLOWED_ORIGINS"] = self.previous_origins

    def test_health_is_readable_by_allowed_frontend(self):
        response = self.client.get("/", headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)

    def test_preflight_allows_application_headers(self):
        response = self.client.options("/api/projects", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertIn("Authorization", response.headers["Access-Control-Allow-Headers"])
        self.assertIn("GET", response.headers["Access-Control-Allow-Methods"])

    def test_untrusted_origin_gets_no_cors_permission(self):
        response = self.client.options("/api/projects", headers={"Origin": "https://other.example"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        self.assertIn("Origin", response.headers["Vary"])

    def test_stub_and_error_responses_are_readable(self):
        for path, status in [("/api/projects", 501), ("/api/unknown", 404)]:
            with self.subTest(path=path):
                response = self.client.get(path, headers={"Origin": ORIGIN})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)

    def test_internal_callbacks_do_not_allow_browser_access(self):
        response = self.client.options("/internal/v1/runs/test/ai-usage", headers={"Origin": ORIGIN})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_empty_allowlist_fails_closed(self):
        app.config["CORS_ALLOWED_ORIGINS"] = set()
        response = self.client.get("/", headers={"Origin": ORIGIN})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
