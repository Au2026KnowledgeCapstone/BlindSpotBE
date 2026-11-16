"""Shapes shared by every resource."""
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_implemented"])
    message: str = Field(examples=["Not yet implemented. Requirements CRUD lands in B4."])


class ErrorResponse(BaseModel):
    """Every error response in this API. Never a raw exception string."""

    error: ErrorBody


class Page(BaseModel, Generic[T]):
    """Cursor-paginated list. Default page size 50, maximum 100."""

    items: list[T]
    next_cursor: str | None = None


class Acknowledged(BaseModel):
    """Returned by endpoints that accept work rather than complete it."""

    status: str = Field(examples=["queued"])
