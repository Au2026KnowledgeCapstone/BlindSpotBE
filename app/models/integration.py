"""Backend-owned dispatch intent and callback inbox. No executor DB access."""
from datetime import datetime
from sqlalchemy import ForeignKey, Text, Integer, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.models.mixins import Identity, Timestamp
import uuid


class Dispatch(Identity, Timestamp, Base):
    __tablename__ = "dispatches"
    __table_args__ = (UniqueConstraint("run_id"), {"schema": "blindspot"})
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blindspot.analysis_runs.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(Text, unique=True)
    # Encrypted immutable envelope includes callback token and credential snapshot.
    encrypted_envelope: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    cost_session_id: Mapped[str | None] = mapped_column(Text)
    finalization: Mapped[dict | None] = mapped_column(JSONB)


class Callback(Identity, Timestamp, Base):
    __tablename__ = "callbacks"
    __table_args__ = (UniqueConstraint("run_id", "sequence"), UniqueConstraint("run_id", "position"), {"schema": "blindspot"})
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blindspot.analysis_runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)


class ResultDetail(Base):
    __tablename__ = "result_details"
    __table_args__ = {"schema": "blindspot"}
    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("blindspot.results.id", ondelete="CASCADE"), primary_key=True)
    outcome: Mapped[dict] = mapped_column(JSONB)
