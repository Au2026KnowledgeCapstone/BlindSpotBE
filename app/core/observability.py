"""Structured JSON logs to stdout. Never log request bodies, Authorization
headers, tokens, or anything from a document upload."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import re
import sys
import time
import uuid

from app.core.config import get_settings

_context: ContextVar[dict] = ContextVar("request_log_context", default={})

FIELDS = {"request_id", "method", "route", "status_code", "duration_ms", "error_type"}


def bind_context(**values) -> object:
    return _context.set({**_context.get(), **{k: v for k, v in values.items() if k in FIELDS}})


def current_context() -> dict:
    return dict(_context.get())


def clean_text(value) -> str:
    text = str(value)
    # Authorization headers and bearer tokens.
    text = re.sub(r"(?i)\bBearer\s+[^\s,;'\"}]+", "Bearer [redacted]", text)
    # JWT-shaped tokens.
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[token]", text)
    # Anything that looks like a credential-shaped key=value or key: value pair.
    text = re.sub(
        r'''(?ix)(["']?(?:password|authorization|cookie|set-cookie|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|token)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}]+)''',
        r"\1[redacted]",
        text,
    )
    return text[:4000]


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:
            message = "Unformattable log record."
        data = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": clean_text(message),
        }
        extra = {**current_context(), **{key: record.__dict__[key] for key in FIELDS if key in record.__dict__}}
        for key, value in extra.items():
            if value is not None:
                data[key] = clean_text(value) if isinstance(value, str) else value
        if record.exc_info and record.exc_info[0]:
            import traceback

            data["error_type"] = record.exc_info[0].__name__
            data["stack"] = [
                {"file": frame.filename.rsplit("/", 1)[-1], "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(record.exc_info[2])[-30:]
            ]
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def configure_logging(service: str) -> None:
    settings = get_settings()
    formatter = JsonFormatter(service)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_blindspot", False):
            root.removeHandler(handler)
            handler.close()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream._blindspot = True
    root.addHandler(stream)
    root.setLevel(settings.log_level)
    # Access logs can include query strings; our own request logger replaces them.
    logging.getLogger("uvicorn.access").disabled = True


class RequestIdMiddleware:
    """Assigns or validates X-Request-ID, echoes it on the response, and logs
    one completion line per request. A caller-supplied id is kept only if it
    is a valid UUID; anything else is replaced."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = next(
            (value.decode("latin1") for key, value in scope.get("headers", []) if key.lower() == b"x-request-id"),
            None,
        )
        try:
            request_id = str(uuid.UUID(incoming)) if incoming else str(uuid.uuid4())
        except (ValueError, AttributeError):
            request_id = str(uuid.uuid4())

        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        started = time.monotonic()
        logger = logging.getLogger("blindspot.api")

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        token = bind_context(request_id=request_id)
        try:
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                logger.exception("Unhandled request failure", extra={"method": scope["method"]})
                raise
            finally:
                logger.info(
                    "Request completed",
                    extra={
                        "method": scope["method"],
                        "route": scope.get("path"),
                        "status_code": status,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    },
                )
        finally:
            _context.reset(token)
