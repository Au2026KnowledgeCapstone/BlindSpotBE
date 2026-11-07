"""Users, projects, membership, invitations, notifications."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["owner", "admin", "member"]
InvitableRole = Literal["admin", "member"]

# Mirrors the CHECK constraints in docs/schema-baseline.sql. Rejecting here
# gives a 422 with a useful message instead of a 500 from Postgres.
Name = Field(min_length=1, max_length=120)
Description = Field(default="", max_length=2000)


class Me(BaseModel):
    user_id: str
    email: str
    display_name: str = ""


class MeUpdate(BaseModel):
    display_name: str = Field(max_length=100)


class Project(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    role: Role | None = Field(default=None, description="The caller's role in this project.")
    organization_id: str | None = None
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Name
    description: str = Description


class ProjectUpdate(BaseModel):
    """A project carries only a name and description. The application's URL
    lives on an environment, not here."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class Member(BaseModel):
    user_id: str
    display_name: str
    role: Role


class Invitation(BaseModel):
    id: str
    project_id: str
    email: str
    role: InvitableRole
    invited_by: str
    expires_at: datetime
    created_at: datetime


class InvitationCreate(BaseModel):
    # Mirrors the CHECK on public.invitations rather than introducing a second
    # definition of a valid address. The database lowercases and trims; so do we.
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    role: InvitableRole = "member"

    @field_validator("email", mode="before")
    @classmethod
    def normalise(cls, value: str) -> str:
        return value.strip().lower() if isinstance(value, str) else value


class Notification(BaseModel):
    id: str
    project_id: str | None
    message: str
    read_at: datetime | None
    created_at: datetime


class NotificationUpdate(BaseModel):
    read: bool


class UnreadCount(BaseModel):
    unread: int


class DashboardCounts(BaseModel):
    """Coverage counts the latest result per requirement, so running the same
    requirement repeatedly does not inflate it. `inconclusive` is derived as
    tested - passed - failed; `untested` stays distinct."""

    total_requirements: int
    approved_requirements: int
    requirements_tested: int
    requirements_passed: int
    requirements_failed: int
    requirements_inconclusive: int
    requirements_untested: int
