import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ServiceError, register_exception_handlers
from app.core.observability import RequestIdMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("something exploded")

    @app.get("/service-error")
    def service_error():
        raise ServiceError("not_found", "Nothing here.", status_code=404)

    @app.post("/validate")
    def validate(value: int):
        return {"value": value}

    return app


client = TestClient(_build_app(), raise_server_exceptions=False)


def test_unhandled_error_cors_only_allows_trusted_origins():
    app = _build_app()
    app.state.auth_settings = SimpleNamespace(trusted_origins=("http://localhost:3000",))
    client = TestClient(app, raise_server_exceptions=False)
    for origin in ("http://localhost:3000", "https://evil.example"):
        response = client.get("/boom", headers={"Origin": origin})
        assert response.status_code == 500
        if origin == "http://localhost:3000":
            assert response.headers["Access-Control-Allow-Origin"] == origin
            assert response.headers["Access-Control-Allow-Credentials"] == "true"
        else:
            assert "Access-Control-Allow-Origin" not in response.headers


def test_deliberate_500_envelope_shape_and_request_id():
    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message"}
    assert "RuntimeError" not in body["error"]["message"]
    assert "something exploded" not in body["error"]["message"]

    request_id = response.headers.get("X-Request-ID")
    assert request_id
    uuid.UUID(request_id)  # valid UUID
    assert request_id in body["error"]["message"]


def test_supplied_request_id_is_echoed_back():
    supplied = str(uuid.uuid4())
    response = client.get("/boom", headers={"X-Request-ID": supplied})

    assert response.headers["X-Request-ID"] == supplied


def test_invalid_supplied_request_id_is_replaced():
    response = client.get("/boom", headers={"X-Request-ID": "not-a-uuid"})

    returned = response.headers.get("X-Request-ID")
    assert returned != "not-a-uuid"
    uuid.UUID(returned)


def test_service_error_envelope():
    response = client.get("/service-error")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Nothing here."}}


def test_validation_error_envelope():
    response = client.post("/validate", params={"value": "not-an-int"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
