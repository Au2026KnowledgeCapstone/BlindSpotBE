from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    database_url: str
    database_pooled_url: str | None = None
    ai_service_url: str | None = None
    environment_credential_encryption_key: str | None = Field(default=None, repr=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("environment_credential_encryption_key")
    @classmethod
    def validate_environment_credential_encryption_key(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip() or None
        if value is not None:
            from cryptography.fernet import Fernet
            try:
                Fernet(value.encode())
            except (ValueError, TypeError):
                raise ValueError("ENVIRONMENT_CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from None
        return value


def _settings_from_sources(*sources: dict) -> Settings:
    values: dict[str, object] = {}
    for name in Settings.model_fields:
        key = name.upper()
        for scope in sources:
            if key in scope and scope[key] is not None:
                values[name] = scope[key]
                break
    return Settings(**values)


@lru_cache
def get_settings() -> Settings:
    # app/core/config.py -> app/core -> app -> repo root
    root_env = Path(__file__).resolve().parents[2] / ".env"
    return _settings_from_sources(os.environ, dotenv_values(root_env))
