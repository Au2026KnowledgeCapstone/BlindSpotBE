"""The API surface is declared, documented, and fails in the right order.

These guard the shape of main.py rather than any behaviour inside it. They are
what stops the surface drifting from backend-api-draft.md while handlers get
implemented one group at a time.
"""
import inspect
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from app.core.auth_config import AuthSettings

ROOT = Path(__file__).resolve().parents[1]
DEV_USER_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app, raise_server_exceptions=False)


def _authenticate(client: TestClient, user_id: str = DEV_USER_ID) -> None:
    """Cookie-session auth, mocked: a configured AuthSettings plus a
    transport that answers /user with a fixed id, matching how
    tests/test_auth.py mocks Supabase. There is no dev bypass in the real
    mechanism (see app/core/auth.py) — tests authenticate the same way
    production does, just against a mock transport instead of Supabase."""
    settings = AuthSettings(
        supabase_url="https://example.supabase.co",
        publishable_key="synthetic-publishable-key",
        development=True,
        frontend_origins=("http://localhost:3000",),
        backend_origin="http://localhost:8000",
    )
    main.app.state.auth_settings = settings
    main.app.state.supabase_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"id": user_id, "email": "dev@example.com"})
    )
    client.cookies.set(settings.access_cookie, "dev-access-token")


def _operations():
    spec = main.app.openapi()
    return [(path, method, op) for path, item in spec["paths"].items() for method, op in item.items()]


def test_every_operation_is_documented():
    missing = [f"{m.upper()} {p}" for p, m, op in _operations() if not op.get("summary")]
    assert not missing, f"operations without a summary: {missing}"


def test_every_operation_is_tagged():
    untagged = [f"{m.upper()} {p}" for p, m, op in _operations() if not op.get("tags")]
    assert not untagged, f"operations without a tag: {untagged}"


def test_unimplemented_endpoints_say_so(client):
    """An unimplemented route returns 501 with a reason — never a fake success.

    The Flask app this replaced returned 200 with echoed input, which read as
    working. That is the failure mode being guarded against.
    """
    _authenticate(client)

    response = client.patch(
        "/api/me",
        json={"display_name": "x"},
        headers={"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"},
    )

    assert response.status_code == 501
    body = response.json()["error"]
    assert body["code"] == "not_implemented"
    assert "lands in" in body["message"]
    assert "data_received" not in response.text


def test_authentication_is_checked_before_implementation(client):
    """401 beats 501. An anonymous caller learns nothing about what exists."""
    response = client.get("/api/projects")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_project_membership_is_checked_before_implementation(client):
    """404 beats 501, so a 501 can never confirm that a project exists to
    someone who is not a member of it."""
    _authenticate(client)

    response = client.get("/api/projects/11111111-2222-3333-4444-555555555555/requirements")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_routes_are_unique():
    seen = set()
    for route in main.app.routes:
        for method in getattr(route, "methods", set()):
            key = (method, route.path)
            assert key not in seen, f"duplicate route: {method} {route.path}"
            seen.add(key)


def test_handlers_stay_thin():
    """Logic belongs in app/services/, not in a route handler.

    Thirty-odd declarations in one file is readable. Thirty handlers carrying
    business logic is not, and that is what this file would become without a
    limit enforced somewhere.
    """
    too_long = []
    for name, obj in vars(main).items():
        if not inspect.isfunction(obj) or obj.__module__ != "main" or name == "todo":
            continue
        source = inspect.getsource(obj).splitlines()
        # Drop the decorator: route metadata is documentation, not logic.
        start = next(
            i for i, line in enumerate(source)
            if line.lstrip().startswith(("def ", "async def "))
        )
        body = source[start + 1 :]
        code = [line for line in body if line.strip() and not line.strip().startswith("#")]
        if len(code) > 15:
            too_long.append(f"{name} ({len(code)} lines)")
    assert not too_long, f"handlers with logic in them: {too_long}"


def test_surface_matches_the_api_draft():
    """Every path in main.py appears in the agreed draft, and vice versa.

    The draft is the contract the frontend builds against. If the two drift,
    one of them is lying, and this is the cheapest place to notice.
    """
    draft = ROOT.parent / "handoffs" / "backend-api-draft.md"
    if not draft.exists():
        pytest.skip("backend-api-draft.md is not checked out alongside this repo")

    declared = {
        re.sub(r"\{[^}]+\}", "{}", path)
        for path in main.app.openapi()["paths"]
    }

    text = draft.read_text()
    text = text.replace("E/", "/api/projects/{pid}/environments/{eid}/")
    documented = {
        re.sub(r"\{[^}]+\}", "{}", match.group(1).split("?")[0])
        for match in re.finditer(r"^(?:GET|POST|PATCH|PUT|DELETE)\s+(\S+)", text, re.MULTILINE)
    }

    undocumented = declared - documented
    unbuilt = documented - declared
    assert not undocumented, f"in main.py but not in the draft: {sorted(undocumented)}"
    assert not unbuilt, f"in the draft but not in main.py: {sorted(unbuilt)}"
