"""BE keeps uploaded documents, per decision — unlike the reference, which
discards originals and keeps only the excerpt."""
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import Identity, Timestamp


class Import(Identity, Timestamp, Base):
    __tablename__ = "imports"
    __table_args__ = {"schema": "blindspot"}

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.projects.id", ondelete="CASCADE"), index=True
    )
    # No DB-level FK to auth.users — see the note in app/models/runs.py.
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class ImportDocument(Identity, Timestamp, Base):
    __tablename__ = "import_documents"
    __table_args__ = (
        CheckConstraint("role IN ('brd','srs','design_spec')", name="ck_import_documents_role"),
        {"schema": "blindspot"},
    )

    import_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.imports.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
