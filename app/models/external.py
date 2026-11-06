"""Shadow tables for objects Supabase owns outside `public` — just enough for
our own foreign keys to resolve against. Never queried through these, never
migrated (the include_object filter in migrations/env.py already keeps
Alembic out of every schema but `blindspot`), never touched otherwise."""
from sqlalchemy import Column, Table
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.db import Base

auth_users = Table(
    "users",
    Base.metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    schema="auth",
)
