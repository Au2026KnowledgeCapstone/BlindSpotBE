"""Durable AI dispatch and callback inbox.

Revision ID: b613ai
Revises: f11ed461fc25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "b613ai"
down_revision = "f11ed461fc25"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("ai_usage", "amount", type_=sa.Numeric(24, 12), existing_type=sa.Numeric(20, 10), schema="blindspot")
    op.add_column("ai_usage", sa.Column("tokens", pg.JSONB(), nullable=True), schema="blindspot")
    op.create_table("dispatches",
        sa.Column("id", pg.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("run_id", pg.UUID(), sa.ForeignKey("blindspot.analysis_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("job_id", sa.Text(), nullable=False, unique=True),
        sa.Column("encrypted_envelope", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("cost_session_id", sa.Text()),
        sa.Column("finalization", pg.JSONB()), schema="blindspot")
    op.create_table("callbacks",
        sa.Column("id", pg.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("run_id", pg.UUID(), sa.ForeignKey("blindspot.analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer()),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"), sa.UniqueConstraint("run_id", "position"), schema="blindspot")
    op.create_index("ix_blindspot_callbacks_run_id", "callbacks", ["run_id"], schema="blindspot")
    op.create_table("result_details",
        sa.Column("result_id", pg.UUID(), sa.ForeignKey("blindspot.results.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("outcome", pg.JSONB(), nullable=False), schema="blindspot")


def downgrade():
    for name in ("result_details", "callbacks", "dispatches"):
        op.drop_table(name, schema="blindspot")
    op.drop_column("ai_usage", "tokens", schema="blindspot")
    op.alter_column("ai_usage", "amount", type_=sa.Numeric(20, 10), existing_type=sa.Numeric(24, 12), schema="blindspot")
