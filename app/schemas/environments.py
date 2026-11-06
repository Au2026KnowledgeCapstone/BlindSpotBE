"""Environments — where an application lives, and how to log into it."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["development", "staging", "production"]

# Matches the CHECK on public.environments.base_url.
BaseUrl = Field(pattern=r"^https?://\S+$", max_length=2048)


class Environment(BaseModel):
    """Credentials are never present on this model. The response says whether
    they are set, not what they are."""

    id: str
    project_id: str
    name: str
    kind: Kind
    base_url: str
    has_credentials: bool
    revision: int
    verified_at: datetime | None
    created_at: datetime


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "staging"
    base_url: str = BaseUrl
    credentials: dict[str, str] | None = Field(
        default=None, description="Write-only. Stored encrypted and never returned."
    )


class EnvironmentUpdate(BaseModel):
    """Changing base_url clears verified_at and bumps revision, which
    invalidates any saved plan built against the old target."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: Kind | None = None
    base_url: str | None = Field(default=None, pattern=r"^https?://\S+$", max_length=2048)
    credentials: dict[str, str] | None = None
