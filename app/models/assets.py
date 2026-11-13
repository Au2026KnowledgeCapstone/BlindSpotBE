"""Retained import manifests and revision-scoped environment verification."""
import uuid
from sqlalchemy import ForeignKey, Text, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.models.mixins import Identity, Timestamp


class ImportRequirement(Base):
    __tablename__ = "import_requirements"
    __table_args__ = {"schema": "blindspot"}
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blindspot.imports.id", ondelete="CASCADE"), primary_key=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blindspot.requirements.id", ondelete="CASCADE"), primary_key=True)


class EnvironmentVerification(Identity, Timestamp, Base):
    __tablename__ = "environment_verifications"
    __table_args__ = {"schema": "blindspot"}
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("public.projects.id", ondelete="CASCADE"))
    environment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("public.environments.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
