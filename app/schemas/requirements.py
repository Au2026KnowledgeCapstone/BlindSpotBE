"""Requirements, their acceptance criteria, and their provenance."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["functional", "ux", "data", "performance", "security"]
Priority = Literal["critical", "high", "medium", "low"]
ApprovalStatus = Literal["draft", "needs_clarification", "approved"]
Verdict = Literal["pass", "fail", "inconclusive"]


class AcceptanceCriterion(BaseModel):
    id: str | None = Field(default=None, description="Omit to create a new criterion.")
    text: str = Field(min_length=1, max_length=2000)
    position: int = 0


class RequirementSource(BaseModel):
    """Provenance. For an imported requirement the excerpt is real source text
    the server selected — not model prose — so a reviewer can check it."""

    kind: Literal["manual", "imported"] = "manual"
    document_name: str | None = None
    document_role: Literal["brd", "srs", "design_spec"] | None = None
    excerpt: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    warnings: list[str] = []


class LatestResult(BaseModel):
    """The most recent completed result for this requirement. Null until
    something has run. Approval is reported separately and does not imply a
    requirement passed."""

    run_id: str
    verdict: Verdict
    completed_at: datetime


class Requirement(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    category: Category
    priority: Priority
    approval_status: ApprovalStatus
    acceptance_criteria: list[AcceptanceCriterion]
    source: RequirementSource
    latest_result: LatestResult | None = None
    created_at: datetime
    updated_at: datetime


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    category: Category = "functional"
    priority: Priority = "medium"
    acceptance_criteria: list[AcceptanceCriterion] = []


class RequirementUpdate(BaseModel):
    """Sending `acceptance_criteria` REPLACES the whole set — the server
    reconciles by id in one transaction. Editing title, description or criteria
    resets approval_status to draft."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    category: Category | None = None
    priority: Priority | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None


class ApprovalRequest(BaseModel):
    approved: bool = True


class ImportDocument(BaseModel):
    id: str
    role: Literal["brd", "srs", "design_spec"]
    filename: str
    sha256: str


class ImportResult(BaseModel):
    """Everything an import produced. Requirements land as drafts; nothing is
    auto-approved."""

    import_id: str
    documents: list[ImportDocument]
    requirements: list[Requirement]
    warnings: list[str] = []
