"""Bodies aiservice posts back to BE. Never called by the frontend.

Field names follow docs/frontend-api-design.md. They are provisional until the
job envelope and event shapes are agreed, and are the subject of B6.

Three rules hold whatever the fields become: persist before publishing,
deduplicate on the event id, and mark cost final only when the expected usage
has actually arrived.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class ExecutionEvent(BaseModel):
    event_id: str = Field(description="Deduplication key. A retry must not create a second row.")
    job_id: str
    attempt: int
    sequence: int = Field(description="Orders events within an attempt.")
    type: str
    occurred_at: datetime
    schema_version: int = 1
    payload: dict


class AIUsageReport(BaseModel):
    usage_id: str = Field(description="Deduplication key. A retry must not add a second charge.")
    event_id: str
    revision: int = Field(default=1, description="A revision replaces an estimate; it does not add to it.")
    cost_session_id: str
    job_id: str
    attempt: int
    provider: str
    model: str
    operation: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    amount: float | None = None
    currency: str = "USD"
    status: str
    occurred_at: datetime


class CostFinalization(BaseModel):
    """Run completion alone is not sufficient — usage can arrive afterwards."""

    event_id: str
    cost_session_id: str
    revision: int = 1
    final_usage_count: int
    closed_at: datetime
