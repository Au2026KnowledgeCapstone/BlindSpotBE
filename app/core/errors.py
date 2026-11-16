"""Error envelope. Every error response is {"error": {"code", "message"}}.
Never return a raw exception string."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("blindspot.api")


class ServiceError(Exception):
    """Raise with a message safe to show the caller. Carries its own status."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _envelope(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_envelope("validation_error", "The request could not be validated."))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    logger.exception("Unhandled request error")
    message = "An unexpected error occurred."
    if request_id:
        message = f"{message} Request ID: {request_id}."
    response = JSONResponse(status_code=500, content=_envelope("internal_error", message))
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
