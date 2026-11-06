"""Contracts captured before the /api rename; no services or credentials needed."""

import json
from pathlib import Path
import re
import unittest

from backend.main import app
from feature_test_support import feature_client, CSRF


CONTRACTS = json.loads(Path(__file__).with_name("route_contracts.json").read_text())


def example_path(path):
    return re.sub(r"{(\w+)}", r"sample-\1", path)


class RouteContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = feature_client()
        cls.client, _, _ = cls.context.__enter__()
        cls.client.cookies.set('bs_access', 'user-a', domain='localhost.local', path='/')
        cls.client.headers.update(CSRF)
        cls.schema = cls.client.get("/openapi.json").json()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def test_complete_operation_inventory(self):
        expected = {(c["path"], c["method"].lower()) for c in CONTRACTS}
        actual = {(path, method) for path, ops in self.schema["paths"].items()
                  for method in ops if not path.startswith("/auth/")}
        self.assertEqual(len(expected), 37)
        self.assertEqual(actual, expected)
        auth_operations = {(path, method) for path, ops in self.schema["paths"].items()
                           if path.startswith("/auth/") for method in ops}
        self.assertEqual(len(auth_operations), 9)
        for route in app.routes:
            path = getattr(route, "path", "")
            self.assertFalse(path == "/api" or path.startswith("/api/"))

    def test_responses_and_methods_match_before_rename(self):
        for contract in CONTRACTS:
            with self.subTest(method=contract["method"], path=contract["path"]):
                url = example_path(contract["path"])
                response = self.client.request(
                    contract["method"], url,
                    json={"text": "hello", "nested": [1, True, None]},
                )
                self.assertEqual(response.status_code, contract["status"])
                self.assertEqual(response.json(), contract["body"])
                if contract["method"] == "GET":
                    head = self.client.head(url)
                    self.assertEqual(head.status_code, contract["status"])
                    self.assertEqual(head.content, b"")
                options = self.client.options(url)
                self.assertEqual(options.status_code, 200)
                self.assertIn(contract["method"], options.headers["allow"])

    def test_tags_deprecations_and_path_parameters(self):
        deprecated = set()
        for contract in CONTRACTS:
            with self.subTest(path=contract["path"], method=contract["method"]):
                operation = self.schema["paths"][contract["path"]][contract["method"].lower()]
                self.assertEqual(operation["tags"], [contract["tag"]])
                self.assertEqual(operation.get("deprecated", False), contract["deprecated"])
                if operation.get("deprecated"):
                    deprecated.add((contract["method"], contract["path"]))
                parameters = {p["name"] for p in operation.get("parameters", [])
                              if p["in"] == "path" and p["required"]}
                self.assertEqual(parameters, set(re.findall(r"{(\w+)}", contract["path"])))
        self.assertEqual(deprecated, {
            ("POST", "/dashboard"), ("POST", "/accounts"),
            ("POST", "/projects/{project_name}"),
            ("POST", "/projects/{project_name}/flows/{flow_id}"),
        })

    def test_framework_urls_unchanged(self):
        for path in ("/docs", "/redoc", "/docs/oauth2-redirect", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
                self.assertEqual(self.client.head(path).status_code, 200)
                self.assertNotIn(path, self.schema["paths"])

    def test_json_parsing_and_dashboard_queries(self):
        for value in (None, False, [1, "example"], {"nested": {"value": 1}}):
            with self.subTest(value=value):
                response = self.client.post("/create-project", content=json.dumps(value),
                                            headers={"content-type": "application/json"})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["data_received"], value)
        self.assertEqual(self.client.post("/create-project", content="{",
                         headers={"content-type": "application/json"}).status_code, 400)
        self.assertEqual(self.client.post("/create-project", content="{}",
                         headers={"content-type": "text/plain"}).status_code, 415)
        response = self.client.get("/dashboard", params={
            "project_id": "project-1", "environment_id": "env-1", "timezone": "Asia/Kolkata",
        })
        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["project_id"], "project-1")
        self.assertEqual(response.json()["environment_id"], "env-1")
        self.assertEqual(response.json()["timezone"], "Asia/Kolkata")


if __name__ == "__main__":
    unittest.main()
