import json
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import sentry_sdk

from app.core.config import Settings, _settings_from_sources
from app.core.telemetry import configure_telemetry, running_under_pytest, safe_path, scrub_event
from app.core.observability import RequestIdMiddleware, current_context


def test_no_dsn_does_not_enable_export(monkeypatch):
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected init")))
    assert configure_telemetry(Settings(database_url="sqlite://"), allow_in_tests=True) is False


def test_test_runs_never_export_even_with_a_dsn_configured(monkeypatch):
    """Importing `main` configures telemetry, and several test modules import
    `main`. A CI runner with SENTRY_DSN set must not ship test traffic to the
    real project, so the DSN alone is not enough to enable export."""
    assert running_under_pytest() is True
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected init")))
    settings = Settings(database_url="sqlite://", sentry_dsn="https://public@o1.ingest.sentry.io/1")
    assert configure_telemetry(settings) is False


def test_safe_path_keeps_route_templates_distinct():
    # A word allowlist collapsed these onto one another, which merged unrelated
    # endpoints into a single Sentry transaction.
    assert safe_path("/internal/v1/runs/{runid}/ai-usage") == "/internal/v1/runs/{runid}/ai-usage"
    assert safe_path("/internal/v1/runs/{runid}/execution-events") == "/internal/v1/runs/{runid}/execution-events"
    assert safe_path("/projects/{pid}/imports/{iid}/documents/{did}") == "/projects/{pid}/imports/{iid}/documents/{did}"
    assert safe_path("/notifications/unread-count") == "/notifications/unread-count"
    assert safe_path("/openapi.json") == "/openapi.json"
    assert safe_path("/docs") == "/docs"
    assert safe_path("/") == "/"


def test_every_route_keeps_a_unique_sanitized_name():
    import main

    paths = {path for path in (getattr(route, "path", None) for route in main.app.routes) if path}
    collapsed = {}
    for path in paths:
        collapsed.setdefault(safe_path(path), set()).add(path)
    assert not {name: sources for name, sources in collapsed.items() if len(sources) > 1}


def test_safe_path_masks_concrete_identifiers_and_credentials():
    assert safe_path("/projects/11111111-2222-3333-4444-555555555555/imports") == "/projects/{id}/imports"
    assert safe_path("/evidence/42") == "/evidence/{id}"
    assert safe_path("/users/user%40example.com") == "/users/{id}"
    assert safe_path("/downloads/gAAAAABnZ0_opaque_fernet_token") == "/downloads/[redacted]"
    assert safe_path("/auth/callback/signup/one-time-transaction-id") == "/auth/callback/[redacted]/[redacted]"
    # Query strings and non-string input must never reach the output.
    assert safe_path("https://api.test/projects/abc?code=secret&email=a@b.c") == "/projects/abc"
    assert safe_path(None) == "/"


def test_sdk_is_configured_to_not_collect_pii_in_the_first_place():
    """A bare `False` leaves the SDK's default denylist mode on, and
    `include_local_variables` is ignored once `data_collection` is set."""
    configure_telemetry(Settings(database_url="sqlite://", sentry_dsn="https://public@localhost/1"), allow_in_tests=True)
    try:
        collection = sentry_sdk.get_client().options["data_collection"]
        assert collection["user_info"] is False
        assert collection["cookies"]["mode"] == "off"
        assert collection["http_headers"]["request"]["mode"] == "off"
        assert collection["url_query_params"]["mode"] == "off"
        assert collection["http_bodies"] == []
        assert collection["stack_frame_variables"] is False
        assert collection["frame_context_lines"] == 0
        assert collection["database_query_data"] is False
    finally:
        sentry_sdk.get_client().close()


def test_buffered_telemetry_is_flushed_on_shutdown():
    from sentry_sdk.integrations.atexit import AtexitIntegration
    from sentry_sdk.integrations.excepthook import ExcepthookIntegration

    configure_telemetry(Settings(database_url="sqlite://", sentry_dsn="https://public@localhost/1"), allow_in_tests=True)
    try:
        client = sentry_sdk.get_client()
        # Without these the span/log batchers (5s window) and the transport
        # queue are never drained on SIGTERM, losing the telemetry that
        # explains the shutdown, and a fatal exception is never reported.
        assert client.get_integration(AtexitIntegration) is not None
        assert client.get_integration(ExcepthookIntegration) is not None
    finally:
        sentry_sdk.get_client().close()


def test_optional_telemetry_config_cannot_break_startup():
    base = {"DATABASE_URL": "sqlite://"}
    # Blank means "use the default", as documented for the adjacent keys.
    assert _settings_from_sources({**base, "SENTRY_TRACES_SAMPLE_RATE": ""}).sentry_traces_sample_rate == 0.1
    assert _settings_from_sources({**base, "SENTRY_ENVIRONMENT": ""}).sentry_environment == "development"
    # A bare or comma-separated regex is accepted rather than failing boot.
    targets = _settings_from_sources({**base, "SENTRY_TRACE_PROPAGATION_TARGETS": "^https://a/, ^https://b/"})
    assert targets.sentry_trace_propagation_targets == ["^https://a/", "^https://b/"]
    assert _settings_from_sources({**base, "SENTRY_TRACE_PROPAGATION_TARGETS": '["^https://a/"]'}).sentry_trace_propagation_targets == ["^https://a/"]
    # An uncompilable pattern would raise from re.search() on every outbound
    # request, so it is dropped instead of propagated into the SDK.
    assert _settings_from_sources({**base, "SENTRY_TRACE_PROPAGATION_TARGETS": "*** bad regex ("}).sentry_trace_propagation_targets == []
    assert _settings_from_sources({**base, "SENTRY_TRACE_PROPAGATION_TARGETS": ""}).sentry_trace_propagation_targets == []


def test_unsampled_requests_do_not_log_phantom_trace_ids():
    """An unsampled request gets a NoOpStreamedSpan whose ids are minted
    lazily and never reach Sentry; logging them sends engineers chasing
    traces that do not exist."""
    configure_telemetry(Settings(database_url="sqlite://", sentry_dsn="https://public@localhost/1",
                                 sentry_traces_sample_rate=0), allow_in_tests=True)
    try:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)
        seen = {}

        @app.get("/projects/{pid}/imports")
        async def imports(pid: str):
            seen.update(current_context())
            return {}

        TestClient(app).get("/projects/abc/imports", headers={"sentry-trace": f"{'a' * 32}-{'b' * 16}-0"})
        assert "request_id" in seen
        assert "trace_id" not in seen and "span_id" not in seen
    finally:
        sentry_sdk.get_client().close()


def test_scrubber_leaves_non_request_events_unlabelled():
    event = scrub_event({"exception": {"values": [{"type": "RuntimeError", "value": "secret"}]}})
    # Fabricating a request context mislabels startup/worker errors as HTTP.
    assert "request" not in event
    assert "contexts" not in event


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
    assert client.options("/auth/signup", headers={**headers, "Origin": "https://untrusted.example.com"}).status_code == 403


def test_real_sdk_continues_browser_trace_and_instruments_outbound_http(caplog):
    from sentry_sdk.transport import Transport

    envelopes = []

    class MemoryTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    settings = Settings(database_url="sqlite://", sentry_dsn="https://public@localhost/1", sentry_traces_sample_rate=1,
                        sentry_trace_propagation_targets=[r"^https://supabase\.example\.com/"])
    configure_telemetry(settings, allow_in_tests=True)
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
