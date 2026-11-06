"""Public schemas deliberately exclude sessions, tokens and user metadata."""
from typing import Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    # Login must accept passwords of existing accounts regardless of newer signup policy.
    password: Annotated[SecretStr, Field(min_length=1, max_length=4096)]


class SignupCredentials(Credentials):
    password: Annotated[SecretStr, Field(min_length=8, max_length=4096)]


class User(BaseModel):
    id: UUID
    email: EmailStr | None = None


class AuthResult(BaseModel):
    user: User | None = None
    authenticated: bool
    confirmation_required: bool = False


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(BaseModel):
    message: str


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: Annotated[SecretStr, Field(min_length=8, max_length=4096)]

