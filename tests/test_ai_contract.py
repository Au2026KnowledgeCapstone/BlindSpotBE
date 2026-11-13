"""Browser-facing headers required by run retries and event replay."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.auth import register_auth
from app.core.auth_config import AuthSettings


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
