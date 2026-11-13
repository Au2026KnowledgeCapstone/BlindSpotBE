"""Idempotent product submissions and honest unknown execution duration.

Revision ID: c614retry
Revises: b613ai
"""
from alembic import op
import sqlalchemy as sa

revision = "c614retry"
down_revision = "b613ai"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dispatches", sa.Column("submission_key", sa.Text()), schema="blindspot")
    op.add_column("dispatches", sa.Column("request_fingerprint", sa.Text()), schema="blindspot")
    op.create_unique_constraint("uq_dispatches_submission_key", "dispatches", ["submission_key"], schema="blindspot")
    op.alter_column("results", "duration_ms", nullable=True, schema="blindspot")


def downgrade():
    op.execute("UPDATE blindspot.results SET duration_ms = 0 WHERE duration_ms IS NULL")
    op.alter_column("results", "duration_ms", nullable=False, schema="blindspot")
    op.drop_constraint("uq_dispatches_submission_key", "dispatches", schema="blindspot")
    op.drop_column("dispatches", "request_fingerprint", schema="blindspot")
    op.drop_column("dispatches", "submission_key", schema="blindspot")
