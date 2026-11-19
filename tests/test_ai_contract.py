"""Browser-facing headers required by run retries and event replay."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.auth import register_auth
from app.core.auth_config import AuthSettings
from fastapi import Depends, UploadFile, File
from app.core.auth import csrf_guard
import pytest


def test_cors_allows_idempotency_and_event_replay_headers():
    app = FastAPI()
    register_auth(app, AuthSettings(supabase_url="https://example.supabase.co", publishable_key="test",
        development=True, frontend_origins=("http://localhost:3000",), backend_origin="http://localhost:8000"))
    client = TestClient(app)
    response = client.options("/projects/test/environments/test/runs", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-protection,idempotency-key,last-event-id"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("origin,csrf,expected", [
    ("http://localhost:3000", "1", 200),
    ("https://evil.example", "1", 403),
    ("http://localhost:3000", "", 403),
])
def test_multipart_import_keeps_csrf_checks(origin, csrf, expected):
    app = FastAPI()
    register_auth(app, AuthSettings(supabase_url="https://example.supabase.co", publishable_key="test",
        development=True, frontend_origins=("http://localhost:3000",), backend_origin="http://localhost:8000"))

    @app.post("/projects/{pid}/imports", dependencies=[Depends(csrf_guard)])
    async def upload(pid: str, brd: UploadFile = File()):
        return {"filename": brd.filename}

    @app.post("/other", dependencies=[Depends(csrf_guard)])
    async def other():
        return {}

    client = TestClient(app)
    headers = {"Origin": origin, "X-CSRF-Protection": csrf}
    response = client.post("/projects/test/imports", files={"brd": ("BRD.md", b"Requirements")}, headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {"filename": "BRD.md"}
        assert client.post("/other", files={"brd": ("BRD.md", b"Requirements")}, headers=headers).status_code == 415
