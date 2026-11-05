import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedUser, DevTokenVerifier, current_user, get_token_verifier
from app.core.config import get_settings
from app.core.errors import register_exception_handlers


@pytest.fixture(autouse=True)
def _clear_caches():
    get_settings.cache_clear()
    get_token_verifier.cache_clear()
    yield
    get_settings.cache_clear()
    get_token_verifier.cache_clear()


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/api/me")
    def me(user: AuthenticatedUser = Depends(current_user)):
        return {"user_id": user.user_id, "email": user.email}

    return app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/db")
    return TestClient(_build_app())


def test_no_authorization_header_is_401(client):
    response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_dev_auth_user_id_unset_is_401_even_with_header(client, monkeypatch):
    monkeypatch.delenv("DEV_AUTH_USER_ID", raising=False)

    response = client.get("/api/me", headers={"Authorization": "Bearer anything"})

    assert response.status_code == 401


def test_dev_auth_user_id_set_yields_that_user(client, monkeypatch):
    monkeypatch.setenv("DEV_AUTH_USER_ID", "user-123")

    response = client.get("/api/me", headers={"Authorization": "Bearer whatever-value"})

    assert response.status_code == 200
    assert response.json()["user_id"] == "user-123"


def test_dev_auth_user_id_against_non_local_db_refuses_to_start(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@db.example.com:5432/db")
    monkeypatch.setenv("DEV_AUTH_USER_ID", "user-123")

    with pytest.raises(RuntimeError, match="DEV_AUTH_USER_ID"):
        DevTokenVerifier()
