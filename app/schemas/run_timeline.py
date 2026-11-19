from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class PlannedStep(BaseModel):
    index: int = Field(ge=0, le=14)
    action: str = Field(max_length=80)
    intent: str = Field(max_length=1000)
    target: str = Field(default="", max_length=1000)
    expected_change: str = Field(default="", max_length=80)


class ProgressEvent(BaseModel):
    position: int = Field(gt=0)
    timestamp: datetime
    phase: str = Field(max_length=80)
    status: Literal["running", "passed", "planned", "inconclusive", "failed", "info"]
    message: str = Field(max_length=1000)
    requirement_id: str | None = Field(default=None, max_length=128)
    step_index: int | None = Field(default=None, ge=0, le=14)
    action: str | None = Field(default=None, max_length=80)
    target: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)
    steps: list[PlannedStep] = Field(default_factory=list, max_length=15)


class RunTimeline(BaseModel):
    job_id: str
    events: list[ProgressEvent] = Field(max_length=100)
    next_cursor: int = Field(ge=0)
