"""Opt-in tracing. Export operational metadata, never authentication payloads."""
import re
import sys
from urllib.parse import urlsplit

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

# Route templates arrive as "/projects/{pid}/imports"; concrete URLs as
# "/projects/<uuid>/imports". Placeholders carry no data and must survive
# untouched, or distinct endpoints collapse into one transaction name.
_PLACEHOLDER = re.compile(r"^\{[^/]*\}$")
_UUID = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEX = re.compile(r"(?i)^[0-9a-f]{24,}$")
# Lowercase words joined by - or . — the shape of every static path segment we
# serve ("imports", "ai-cost-finalizations", "openapi.json"). Anything else is
# treated as a value, not a route name.
_SLUG = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
_MAX_SEGMENT = 32
# Concrete segments after these are one-time credentials: OAuth transaction
# ids and signed download tokens.
_CREDENTIAL_PARENTS = frozenset({"callback", "downloads"})


def _safe_segment(part: str) -> str:
    if not part or _PLACEHOLDER.match(part):
        return part
    if part.isdigit() or _UUID.match(part) or _HEX.match(part):
        return "{id}"
    if len(part) <= _MAX_SEGMENT and _SLUG.match(part):
        return part
    return "{id}"


def safe_path(value) -> str:
    """Reduce a URL or route template to a low-cardinality, credential-free path."""
    path = urlsplit(value if isinstance(value, str) else "/").path or "/"
    parts, redact = [], False
    for part in path.split("/"):
        placeholder = not part or bool(_PLACEHOLDER.match(part))
        parts.append("[redacted]" if redact and not placeholder else _safe_segment(part))
        redact = redact or part in _CREDENTIAL_PARENTS
    return "/".join(parts)


def scrub_span(span: dict) -> dict:
    # SQL and HTTP descriptions/data may contain passwords, emails or queries.
    span["description"] = span.get("op", "operation")
    data = span.get("data", {})
    span["data"] = {key: data[key] for key in ("http.request.method", "http.response.status_code") if key in data}
    return span


def scrub_event(event: dict, hint=None) -> dict:
    event["server_name"] = "blindspot-api"
    for key in ("user", "extra", "breadcrumbs", "logentry", "modules"):
        event.pop(key, None)
    event["tags"] = {key: value for key, value in (event.get("tags") or {}).items() if key in {"request_id", "service"}}
    # Only rewrite a request context that exists; fabricating one would label
    # every startup/worker error as an HTTP request to "/".
    if event.get("request"):
        request = event["request"]
        event["request"] = {"method": request.get("method"), "url": safe_path(request.get("url"))}
    trace = {key: value for key, value in (event.get("contexts") or {}).get("trace", {}).items() if key in {"trace_id", "span_id", "parent_span_id", "op", "status"}}
    if trace:
        event["contexts"] = {"trace": trace}
    else:
        event.pop("contexts", None)
    if "message" in event:
        event["message"] = "Application error (details withheld; inspect stack and request ID)."
    for exception in event.get("exception", {}).get("values", []):
        exception["value"] = "[redacted]"
        for frame in exception.get("stacktrace", {}).get("frames", []):
            for key in list(frame):
                if key not in {"filename", "function", "module", "lineno", "colno", "in_app"}:
                    frame.pop(key, None)
    if "transaction" in event:
        event["transaction"] = safe_path(event["transaction"])
    for span in event.get("spans", []):
        scrub_span(span)
    return event


def scrub_log(log: dict, hint=None) -> dict | None:
    # Only our fixed completion message enters Sentry Logs; SDK/third-party
    # logging and arbitrary application messages cannot export payloads.
    if log.get("body") != "Request completed":
        return None
    attrs = log.get("attributes", {})
    allowed = {"request_id", "trace_id", "span_id", "method", "route", "status_code", "duration_ms", "sentry.trace.parent_span_id"}
    log["attributes"] = {key: value for key, value in attrs.items() if key in allowed}
    return log


def scrub_streamed_span(span: dict, hint=None) -> dict:
    attrs = span.get("attributes", {})
    allowed = {"sentry.op", "sentry.origin", "sentry.kind", "http.request.method", "http.response.status_code", "request_id"}
    span["attributes"] = {key: value for key, value in attrs.items() if key in allowed}
    # Names may contain raw URLs or SQL. Retain a sanitized route for servers.
    span["name"] = safe_path(span.get("name", "/")) if span.get("is_segment") else "operation"
    return span


def running_under_pytest() -> bool:
    """Whether this process is running the test suite.

    `main` calls `configure_telemetry` at import time and six test modules
    import `main`, so on a CI runner that defines SENTRY_DSN the suite would
    otherwise initialise the real SDK and ship an envelope for every test
    request: real issues filed against test fixtures, release health and quota
    burned by CI, and test runs made dependent on an outbound network call.

    Detecting pytest rather than reading APP_ENV is deliberate. APP_ENV is a
    closed enum — `AuthSettings.from_env()` raises on anything that is not
    `development` or `production` — so an `APP_ENV=test` value would break auth
    configuration outright. An env-var opt-out would also only protect CI if
    somebody remembers to set it in every workflow; this needs no configuration
    anywhere and so is safe by construction.
    """
    return "pytest" in sys.modules


def configure_telemetry(settings, *, allow_in_tests: bool = False) -> bool:
    """Initialise Sentry. No-op without a DSN, and a no-op under pytest.

    Tests that exercise the SDK on purpose pass `allow_in_tests=True` together
    with an explicit Settings object, a localhost DSN and an in-memory
    transport, so they never reach the network.
    """
    if not settings.sentry_dsn:
        return False
    if running_under_pytest() and not allow_in_tests:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        trace_lifecycle="stream",
        # A bare False is NOT an opt-out for the key/value categories: the SDK
        # resolves `cookies`/`http_headers`/`url_query_params` with
        # `d.get(key) or {}`, so False falls back to its default denylist mode
        # and keeps collecting everything whose name is not obviously secret.
        # Only {"mode": "off"} disables them. Likewise `include_local_variables`
        # and `include_source_context` are ignored once `data_collection` is
        # set, so the frame opt-outs have to be repeated here.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {"request": {"mode": "off"}},
            "url_query_params": {"mode": "off"},
            "http_bodies": [],
            "stack_frame_variables": False,
            "frame_context_lines": 0,
            "database_query_data": False,
            "graphql": {"document": False, "variables": False},
            "gen_ai": {"inputs": False, "outputs": False},
            "queues": False,
        },
        max_request_body_size="never",
        include_local_variables=False,
        # Opt out of the noisy/PII-prone default integrations (logging, modules,
        # argv, stdlib, threading) but keep the three that are load-bearing:
        # atexit flushes the span/log batchers and the transport queue on
        # SIGTERM, excepthook reports a fatal uncaught exception, and dedupe
        # stops one exception being reported by two integrations.
        default_integrations=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            HttpxIntegration(),
            SqlalchemyIntegration(),
            AtexitIntegration(),
            ExcepthookIntegration(),
            DedupeIntegration(),
        ],
        # Don't propagate correlation headers to arbitrary application URLs.
        trace_propagation_targets=settings.sentry_trace_propagation_targets,
        before_send=scrub_event,
        before_send_span=scrub_streamed_span,
        # Span streaming emits no transaction events, so this is a guard for the
        # day `trace_lifecycle` changes: without it transactions (and the span
        # descriptions they embed) would bypass scrubbing entirely.
        before_send_transaction=scrub_event,
        enable_logs=True,
        before_send_log=scrub_log,
    )
    return True
