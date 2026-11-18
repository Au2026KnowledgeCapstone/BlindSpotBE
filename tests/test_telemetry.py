import json
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import sentry_sdk

from app.core.config import Settings
from app.core.telemetry import configure_telemetry, scrub_event
from app.core.observability import RequestIdMiddleware, current_context


def test_no_dsn_does_not_enable_export(monkeypatch):
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected init")))
    assert configure_telemetry(Settings(database_url="sqlite://")) is False


def test_scrubber_removes_payloads_and_keeps_trace_linkage():
    event = scrub_event({
        "user": {"email": "secret"}, "extra": {"token": "secret"}, "breadcrumbs": [{"message": "secret"}],
        "request": {"url": "https://api.test/auth/callback/signup/secret?code=secret", "headers": {"Cookie": "secret"}, "data": "secret"},
        "contexts": {"trace": {"trace_id": "abc", "span_id": "def", "data": "secret"}},
        "exception": {"values": [{"type": "RuntimeError", "value": "secret", "stacktrace": {"frames": [{"function": "signup", "vars": {"password": "secret"}}]}}]},
        "spans": [{"op": "db", "description": "secret", "data": {"query": "secret"}}],
    })
    assert "secret" not in json.dumps(event)
    assert event["contexts"]["trace"]["trace_id"] == "abc"
    assert event["exception"]["values"][0]["stacktrace"]["frames"][0]["function"] == "signup"


def test_trace_preflight_keeps_existing_origin_restrictions(monkeypatch):
    import base64
    from app.core.auth import register_auth
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_FRONTEND_ORIGINS", "https://frontend.example.com")
    monkeypatch.setenv("AUTH_BACKEND_ORIGIN", "https://backend.example.com")
    monkeypatch.setenv("AUTH_FLOW_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    app = FastAPI()
    register_auth(app)
    client = TestClient(app)
    headers = {"Origin": "https://frontend.example.com", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "sentry-trace,baggage,x-request-id,x-csrf-protection"}
    response = client.options("/auth/signup", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://frontend.example.com"
    assert client.options("/auth/signup", headers={**headers, "Origin": "https://untrusted.example.com"}).status_code == 400


def test_real_sdk_continues_browser_trace_and_instruments_outbound_http(caplog):
    from sentry_sdk.transport import Transport

    envelopes = []

    class MemoryTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    settings = Settings(database_url="sqlite://", sentry_dsn="https://public@localhost/1", sentry_traces_sample_rate=1,
                        sentry_trace_propagation_targets=[r"^https://supabase\.example\.com/"])
    configure_telemetry(settings)
    client = sentry_sdk.get_client()
    client.transport = MemoryTransport({})
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    seen = {}

    @app.post("/auth/signup")
    async def signup():
        seen.update(current_context())
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: (seen.update(outbound=dict(req.headers)), httpx.Response(503))[1])) as http:
            await http.post("https://supabase.example.com/auth/v1/signup", json={"password": "secret"})
        sentry_sdk.capture_exception(RuntimeError("secret"))
        return {"ok": False}

    trace_id = "a" * 32
    request_id = str(uuid4())
    try:
        with caplog.at_level(logging.INFO):
            response = TestClient(app).post("/auth/signup", headers={"sentry-trace": f"{trace_id}-{'b' * 16}-1", "X-Request-ID": request_id})
        sentry_sdk.flush()
        assert response.headers["X-Request-ID"] == request_id
        assert seen["trace_id"] == trace_id
        assert seen["outbound"]["sentry-trace"].startswith(trace_id)
        assert any(record.getMessage() == "Request completed" and record.route == "/auth/signup" for record in caplog.records)
        payloads = [item.payload.json for envelope in envelopes for item in envelope.items if item.payload.json]
        assert payloads
        assert any(item.headers.get("type") == "span" for envelope in envelopes for item in envelope.items)
        assert "secret" not in json.dumps(payloads)
        assert any(payload.get("contexts", {}).get("trace", {}).get("trace_id") == trace_id for payload in payloads)
    finally:
        client.close()
