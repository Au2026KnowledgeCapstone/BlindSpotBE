"""Analysis runs and everything scoped underneath one. `project_id` is
carried on every table that also carries its parent's id, and the two are
tied together with a composite FK — e.g. `results(project_id,
analysis_run_id)` referencing `analysis_runs(project_id, id)` — so the
database itself rejects a result attached to another project's run.

`environment_id` below is a plain FK, not composite: the matching
`UNIQUE(project_id, id)` would have to live on `public.environments`, and
`public` gets exactly the two changes approved in B1 Step 1. Cross-project
environment attachment has to be caught in the service layer instead."""
from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import Identity


class AnalysisRun(Identity, Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_analysis_runs_project_id_id"),
        UniqueConstraint("project_id", "run_number", name="uq_analysis_runs_project_run_number"),
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint("engine IN ('mvp','graph','stub')", name="ck_analysis_runs_engine"),
        {"schema": "blindspot"},
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.projects.id", ondelete="CASCADE"), index=True
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.environments.id"), index=True
    )
    # Allocated under a lock on the project row; gapless per project.
    run_number: Mapped[int] = mapped_column(Integer)
    engine: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued", index=True)
    # Frozen at queue time. Never rewritten — history survives later edits.
    requirement_snapshots: Mapped[list] = mapped_column(JSONB)
    # No DB-level FK to auth.users: Supabase does not let a custom role hold
    # privileges on the auth schema (grants to it are silently unwound).
    # Trusted the same way the rest of BE trusts a user id — from the
    # verified JWT, not from the request body.
    requested_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Worker lease, not a user-facing field.
    claim_token: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, server_default="false")
    error: Mapped[str | None] = mapped_column(Text)


class Result(Identity, Base):
    __tablename__ = "results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "analysis_run_id"],
            ["blindspot.analysis_runs.project_id", "blindspot.analysis_runs.id"],
            ondelete="CASCADE",
            name="fk_results_analysis_run_tenancy",
        ),
        ForeignKeyConstraint(
            ["project_id", "requirement_id"],
            ["blindspot.requirements.project_id", "blindspot.requirements.id"],
            name="fk_results_requirement_tenancy",
        ),
        CheckConstraint("verdict IN ('pass','fail','inconclusive')", name="ck_results_verdict"),
        CheckConstraint(
            "classification IN ("
            "'criteria_satisfied','criteria_violated','locator_failure',"
            "'environment_failure','execution_error')",
            name="ck_results_classification",
        ),
        {"schema": "blindspot"},
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    # `inconclusive` is a verdict, not an error — a member of this enum.
    verdict: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(Text)
    observed_behavior: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class CriterionAssessment(Identity, Base):
    __tablename__ = "criterion_assessments"
    __table_args__ = (
        CheckConstraint("verdict IN ('pass','fail','inconclusive')", name="ck_criterion_assessments_verdict"),
        CheckConstraint("source IN ('ai','objective','engine')", name="ck_criterion_assessments_source"),
        {"schema": "blindspot"},
    )

    result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.results.id", ondelete="CASCADE"), index=True
    )
    # Nullable: a criterion can be deleted later through the requirement PATCH
    # reconciliation. The historical assessment must survive that, so this is
    # ON DELETE SET NULL rather than CASCADE.
    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.acceptance_criteria.id", ondelete="SET NULL")
    )
    verdict: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)


class Evidence(Identity, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("type IN ('screenshot','page_text','log')", name="ck_evidence_type"),
        {"schema": "blindspot"},
    )

    result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.results.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(Text)
    observation_id: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True).evaluates_none())


class Action(Identity, Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint("outcome IN ('completed','stopped')", name="ck_actions_outcome"),
        {"schema": "blindspot"},
    )

    result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.results.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.evidence.id", ondelete="SET NULL")
    )
