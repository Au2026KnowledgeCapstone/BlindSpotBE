"""Shared columns. Mirrors the typed-Mapped style in
BlindSpot/backend/app/models/__init__.py, adapted to native Postgres uuid
(our FKs point at public tables whose ids are uuid, not varchar)."""
from datetime import datetime
import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


class Timestamp:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
