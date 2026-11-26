"""Public schemas deliberately exclude sessions, tokens and user metadata.

Ported from feat/backend-auth (backend/auth_schemas.py) onto the app/
layout. Logic unchanged."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
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


class SignupAuthenticated(BaseModel):
    user: User
    authenticated: Literal[True] = True
    confirmation_required: Literal[False] = False


class SignupConfirmationRequired(BaseModel):
    user: None = None
    authenticated: Literal[False] = False
    confirmation_required: Literal[True] = True


SignupResult = Annotated[SignupAuthenticated | SignupConfirmationRequired, Field(discriminator="authenticated")]


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(BaseModel):
    message: str


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class ResetRequest(EmailRequest):
    pass


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    password: Annotated[SecretStr, Field(min_length=8, max_length=4096)]
