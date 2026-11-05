from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, _settings_from_sources, get_settings


def test_settings_load_from_env():
    settings = _settings_from_sources(
        {
            "DATABASE_URL": "postgresql+psycopg2://u:p@localhost:5432/db",
            "DEV_AUTH_USER_ID": "user-123",
            "CORS_ORIGINS": "http://localhost:5173",
            "LOG_LEVEL": "DEBUG",
        }
    )

    assert settings.database_url == "postgresql+psycopg2://u:p@localhost:5432/db"
    assert settings.dev_auth_user_id == "user-123"
    assert settings.cors_origins == "http://localhost:5173"
    assert settings.log_level == "DEBUG"


def test_missing_database_url_fails_loudly():
    with pytest.raises(ValidationError):
        _settings_from_sources({})


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/db")

    first = get_settings()
    second = get_settings()

    assert first is second
    get_settings.cache_clear()


def test_env_example_names_every_field():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example.read_text()
    declared = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    for field_name in Settings.model_fields:
        assert field_name.upper() in declared
