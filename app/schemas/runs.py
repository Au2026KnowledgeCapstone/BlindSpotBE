"""Analysis runs, their per-requirement results, and the evidence behind them."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
Verdict = Literal["pass", "fail", "inconclusive"]
Classification = Literal[
    "criteria_satisfied",
    "criteria_violated",
    "locator_failure",
    "environment_failure",
    "execution_error",
]
Engine = Literal["mvp", "graph", "stub"]


class RequirementSnapshot(BaseModel):
    """Frozen when the run was queued, so history survives later edits."""

    id: str
    title: str
    description: str = ""
    criteria: list[dict[str, str]] = []


class Run(BaseModel):
    id: str
    run_number: int
    project_id: str
    environment_id: str
    status: RunStatus
    cancel_requested: bool = False
    engine: Engine | None = Field(
        default=None, description="Which engine produced this run. Recorded so results stay comparable."
    )
    requirement_snapshots: list[RequirementSnapshot]
    requested_by: str
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    action_count: int = 0
    estimated_cost_usd: float | None = None
    error: str | None = None


class RunCreate(BaseModel):
    """Only approved requirements may be selected, at most ten per run."""

    requirement_ids: list[str] = Field(min_length=1, max_length=10)


class CriterionAssessment(BaseModel):
    """`source` is what lets the frontend render model output differently from
    observed fact. A deterministic check outranks a model judgement."""

    criterion_id: str
    criterion_text: str
    verdict: Verdict
    rationale: str
    source: Literal["ai", "objective", "engine"]
    cited_evidence_ids: list[str] = []


class Action(BaseModel):
    index: int
    kind: str
    description: str
    outcome: Literal["completed", "stopped"]
    evidence_id: str | None = None


class Evidence(BaseModel):
    id: str
    type: Literal["screenshot", "page_text", "log"]
    media_type: str | None = None
    observation_id: str | None = None
    sha256: str | None = None
    captured_at: datetime | None


class Result(BaseModel):
    """One requirement, one run. `observed_behavior` is plain-English fact;
    model reasoning lives in the per-criterion rationales."""

    id: str
    run_id: str
    requirement_id: str
    requirement_title: str
    verdict: Verdict
    classification: Classification
    observed_behavior: str
    criterion_assessments: list[CriterionAssessment]
    actions: list[Action]
    evidence: list[Evidence]
    duration_ms: int | None


class RunUsage(BaseModel):
    run_id: str
    estimated_cost_usd: float | None
    cost_status: str = Field(examples=["pending", "final", "unknown"])
    input_tokens: int | None = None
    output_tokens: int | None = None
