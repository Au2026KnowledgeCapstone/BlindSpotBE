"""Opt-in tracing. Export operational metadata, never authentication payloads."""
from urllib.parse import urlsplit

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration


def safe_path(value: str) -> str:
    # Callback/download path segments can contain one-time credentials.
    path = urlsplit(value).path
    if "/auth/callback/" in path:
        return "/auth/callback/[redacted]"
    if "/downloads/" in path:
        return "/downloads/[redacted]"
    fixed = set("auth signup login logout me refresh recovery password reset-request update callback projects environments applications members invitations notifications onboarding requirements runs results events cancel verify capabilities downloads dashboard token user rest v1".split())
    return "/".join(part if not part or part in fixed or (part.startswith("{") and part.endswith("}")) else "{id}" for part in path.split("/"))


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
    event["tags"] = {key: value for key, value in event.get("tags", {}).items() if key in {"request_id", "service"}}
    request = event.get("request", {})
    event["request"] = {"method": request.get("method"), "url": safe_path(request.get("url", "/"))}
    event["contexts"] = {"trace": {key: value for key, value in event.get("contexts", {}).get("trace", {}).items() if key in {"trace_id", "span_id", "parent_span_id", "op", "status"}}}
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


def configure_telemetry(settings) -> bool:
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        trace_lifecycle="stream",
        data_collection={"user_info": False, "cookies": False, "http_headers": False, "http_bodies": [], "url_query_params": False},
        max_request_body_size="never",
        include_local_variables=False,
        default_integrations=False,
        integrations=[StarletteIntegration(), FastApiIntegration(), HttpxIntegration(), SqlalchemyIntegration()],
        # Don't propagate correlation headers to arbitrary application URLs.
        trace_propagation_targets=settings.sentry_trace_propagation_targets,
        before_send=scrub_event,
        before_send_span=scrub_streamed_span,
        enable_logs=True,
        before_send_log=scrub_log,
    )
    return True
