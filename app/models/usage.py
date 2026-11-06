"""AI cost accounting. `project_id` and `analysis_run_id` are both nullable
with ON DELETE SET NULL, per decision, so cost history outlives the records
it was spent on.

The remaining columns operationalize app.schemas.internal.AIUsageReport —
B6's ingestion target, not specified column-by-column in the B1 handoff, but
needed for this table to be able to hold what that schema already commits to
receiving. `usage_id` is unique: a later revision for the same usage_id
replaces the estimate in place rather than adding a second charge."""
from datetime import datetime
from decimal import Decimal
import uuid

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import Identity, Timestamp


class AIUsage(Identity, Timestamp, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (
        UniqueConstraint("usage_id", name="uq_ai_usage_usage_id"),
        {"schema": "blindspot"},
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.projects.id", ondelete="SET NULL"), index=True
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("blindspot.analysis_runs.id", ondelete="SET NULL"), index=True
    )
    usage_id: Mapped[str] = mapped_column(Text)
    event_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    cost_session_id: Mapped[str] = mapped_column(Text, index=True)
    job_id: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    currency: Mapped[str] = mapped_column(Text, server_default="USD")
    status: Mapped[str] = mapped_column(Text, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
