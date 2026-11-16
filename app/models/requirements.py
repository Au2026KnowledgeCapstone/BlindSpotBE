from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import Identity, Timestamp


class Requirement(Identity, Timestamp, Base):
    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_requirements_project_id_id"),
        CheckConstraint(
            "category IN ('functional','ux','data','performance','security')",
            name="ck_requirements_category",
        ),
        CheckConstraint("priority IN ('critical','high','medium','low')", name="ck_requirements_priority"),
        CheckConstraint(
            "approval_status IN ('draft','needs_clarification','approved')",
            name="ck_requirements_approval_status",
        ),
        {"schema": "blindspot"},
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    category: Mapped[str] = mapped_column(Text, server_default="functional")
    priority: Mapped[str] = mapped_column(Text, server_default="medium")
    approval_status: Mapped[str] = mapped_column(Text, server_default="draft", index=True)
    # Provenance for an imported requirement: document, excerpt, offsets,
    # warnings. See app.schemas.requirements.RequirementSource.
    source: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AcceptanceCriterion(Identity, Base):
    """Its own table, per decision — never written except through the
    requirement PATCH, which reconciles the whole set by id."""

    __tablename__ = "acceptance_criteria"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "requirement_id"],
            ["blindspot.requirements.project_id", "blindspot.requirements.id"],
            ondelete="CASCADE",
            name="fk_acceptance_criteria_requirement_tenancy",
        ),
        {"schema": "blindspot"},
    )

    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
