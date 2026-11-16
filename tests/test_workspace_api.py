"""Canonical cookie-authenticated workspace API contract tests."""
from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from app.core.auth_config import AuthSettings

ORIGIN = "http://localhost:3000"
UID = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
INVITATION = "44444444-4444-4444-8444-444444444444"
USER = {"id": UID, "email": "person@example.com"}
NOW = datetime.now(timezone.utc).isoformat()


def setup_client(handler):
    main.app.state.auth_settings = AuthSettings(
        supabase_url="https://example.supabase.co",
        publishable_key="synthetic-publishable-key",
        development=True,
        frontend_origins=(ORIGIN,),
        backend_origin="http://localhost:8000",
    )
    main.app.state.supabase_transport = httpx.MockTransport(handler)
    client = TestClient(main.app, raise_server_exceptions=False)
    client.cookies.set("bs_access", "verified-cookie-token")
    return client


def project_row():
    return {"id": PROJECT, "name": "Example", "description": "", "owner_id": UID, "created_at": NOW}


def test_project_collection_uses_cookie_and_canonical_page_contract():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        assert request.headers["authorization"] == "Bearer verified-cookie-token"
        assert request.headers["apikey"] == "synthetic-publishable-key"
        assert "service_role" not in request.headers["apikey"]
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=[project_row() | {"owner_id": "99999999-9999-4999-8999-999999999999"}])
        if request.url.path.endswith("/project_members"):
            return httpx.Response(200, json=[{"project_id": PROJECT, "role": "member"}])
        raise AssertionError(request.url.path)

    response = setup_client(handler).get("/projects", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["next_cursor"] is None
    assert len(page["items"]) == 1
    assert page["items"][0]["role"] == "member"
    assert response.headers["cache-control"] == "no-store"
    assert "verified-cookie-token" not in response.text
    assert "service_role" not in response.text
    assert len([r for r in seen if r.url.path == "/auth/v1/user"]) == 1


def test_pending_invitation_inbox_scopes_to_verified_email():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        assert request.url.path == "/rest/v1/invitations"
        assert request.url.params["email"] == "eq.person@example.com"
        assert request.url.params["accepted_at"] == "is.null"
        assert request.url.params["expires_at"].startswith("gt.")
        return httpx.Response(200, json=[{"id": INVITATION, "project_id": PROJECT, "email": "person@example.com", "role": "member", "invited_by": UID, "expires_at": NOW, "created_at": NOW}])

    response = setup_client(handler).get("/invitations", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == INVITATION


def test_members_use_supported_bounded_profile_lookup_not_embedding():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=[project_row()])
        if request.url.path.endswith("/project_members"):
            assert "profiles(" not in request.url.params.get("select", "")
            return httpx.Response(200, json=[{"user_id": UID, "role": "member"}])
        if request.url.path.endswith("/profiles"):
            assert request.url.params["user_id"] == f"in.({UID})"
            return httpx.Response(200, json=[{"user_id": UID, "display_name": "Pat"}])
        raise AssertionError(request.url.path)

    response = setup_client(handler).get(f"/projects/{PROJECT}/members", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [{"user_id": UID, "role": "member", "display_name": "Pat"}]


def test_accept_invitation_calls_atomic_rpc_only_after_csrf():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        return httpx.Response(200, json={"user_id": UID, "role": "member"})

    client = setup_client(handler)
    path = f"/invitations/{INVITATION}/accept"
    assert client.post(path, json={}, headers={"Origin": ORIGIN}).status_code == 403
    accepted = client.post(path, json={}, headers={"Origin": ORIGIN, "X-CSRF-Protection": "1"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"user_id": UID, "role": "member", "display_name": ""}
    rpc = next(r for r in requests if r.url.path.endswith("/rpc/accept_invitation"))
    assert rpc.method == "POST"


def test_invalid_cookie_rejected_by_real_current_user_dependency():
    client = setup_client(lambda request: httpx.Response(401, json={"message": "ignored upstream body"}))
    response = client.get("/projects", headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert "ignored upstream body" not in response.text


def test_upstream_outage_is_sanitized_503():
    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        raise httpx.ConnectError("synthetic detail", request=request)

    response = setup_client(handler).get("/projects", headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert "synthetic detail" not in response.text


def test_environment_application_id_is_nullable_and_credentials_are_write_only():
    from cryptography.fernet import Fernet
    from app.core.config import Settings
    from app.services.workspace_routes import EnvironmentInput, _environment_out

    key = Fernet.generate_key().decode()
    settings = Settings(database_url="postgresql://unused", environment_credential_encryption_key=key)
    assert settings.environment_credential_encryption_key == key
    assert EnvironmentInput(name="Stage", base_url="https://example.invalid").application_id is None
    from uuid import uuid4
    row = {"id": uuid4(), "project_id": uuid4(), "name": "Stage", "kind": "staging", "base_url": "https://example.invalid", "created_at": NOW, "revision": 1, "verified_at": None, "encrypted_credentials": "ciphertext"}
    dto = _environment_out(row)
    assert dto["id"] == str(row["id"]) and dto["project_id"] == str(row["project_id"])
    assert "encrypted_credentials" not in dto and dto["has_credentials"]
    with pytest.raises(ValueError):
        Settings(database_url="postgresql://unused", environment_credential_encryption_key="invalid")


def test_environment_create_uses_server_db_encryption_and_nullable_application(monkeypatch):
    import json
    from cryptography.fernet import Fernet
    from app.core.config import Settings
    from app.core.db import get_db

    key = Fernet.generate_key().decode()
    settings = Settings(database_url="postgresql://unused", environment_credential_encryption_key=key)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    inserted = {}
    project_id = UUID(PROJECT)
    environment_id = UUID("55555555-5555-4555-8555-555555555555")

    class Result:
        def first(self):
            return type("Membership", (), {"role": "admin"})()

        def mappings(self):
            return self

        def one(self):
            return {
                "id": environment_id, "project_id": project_id, "name": "Stage",
                "kind": "staging", "base_url": "https://example.invalid",
                "encrypted_credentials": inserted["encrypted_credentials"], "revision": 1,
                "verified_at": None, "created_at": NOW,
            }

    class Db:
        def execute(self, statement, params):
            if "INSERT INTO public.environments" in str(statement):
                inserted.update(params)
            return Result()

        def commit(self):
            inserted["committed"] = True

    db = Db()
    main.app.dependency_overrides[get_db] = lambda: db
    try:
        def handler(request):
            if request.url.path == "/auth/v1/user":
                return httpx.Response(200, json=USER)
            raise AssertionError(f"unexpected PostgREST call: {request.url}")

        response = setup_client(handler).post(
            f"/projects/{PROJECT}/environments",
            json={"name": "Stage", "base_url": "https://example.invalid", "credentials": {"username": "u", "password": "p"}},
            headers={"Origin": ORIGIN, "X-CSRF-Protection": "1"},
        )
    finally:
        main.app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 201, response.text
    assert inserted["application_id"] is None
    assert inserted["committed"] is True
    assert Fernet(key.encode()).decrypt(inserted["encrypted_credentials"].encode()) == json.dumps(
        {"username": "u", "password": "p"}, separators=(",", ":")
    ).encode()
    assert response.json()["has_credentials"] is True
    assert "encrypted_credentials" not in response.text and "password" not in response.text


def test_workspace_hides_projects_outsider():
    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        if request.url.path.endswith("/projects"):
            return httpx.Response(200, json=[project_row() | {"owner_id": "99999999-9999-4999-8999-999999999999"}])
        if request.url.path.endswith("/project_members"):
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)

    response = setup_client(handler).get(f"/projects/{PROJECT}/workspace", headers={"Origin": ORIGIN})
    assert response.status_code == 404


def test_notification_count_uses_exact_postgrest_count():
    def handler(request):
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=USER)
        assert request.url.path == "/rest/v1/notifications"
        assert request.headers["prefer"] == "count=exact"
        return httpx.Response(206, json=[{"id": "placeholder"}], headers={"Content-Range": "0-0/7"})

    response = setup_client(handler).get("/notifications/unread-count", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert response.json() == {"unread": 7}


def test_project_routes_are_canonical_not_workspace_aliases():
    paths = set(main.app.openapi()["paths"])
    assert "/projects" in paths
    assert "/workspace-api/bootstrap" not in paths
    assert "/projects/{pid}/workspace" in paths


