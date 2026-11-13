"""Retained import manifests and revision-safe verification records.

Revision ID: d715assets
Revises: c614retry
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "d715assets"
down_revision = "c614retry"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("evidence", "captured_at", nullable=True, server_default=None, schema="blindspot")
    op.add_column("imports", sa.Column("request_key", sa.Text()), schema="blindspot")
    op.add_column("imports", sa.Column("fingerprint", sa.Text()), schema="blindspot")
    op.add_column("imports", sa.Column("status", sa.Text(), nullable=False, server_default="completed"), schema="blindspot")
    op.add_column("imports", sa.Column("warnings", pg.JSONB(), nullable=False, server_default="[]"), schema="blindspot")
    op.create_unique_constraint("uq_imports_request_key", "imports", ["request_key"], schema="blindspot")
    op.create_table("import_requirements",
        sa.Column("import_id", pg.UUID(), sa.ForeignKey("blindspot.imports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("requirement_id", pg.UUID(), sa.ForeignKey("blindspot.requirements.id", ondelete="CASCADE"), primary_key=True), schema="blindspot")
    op.create_table("environment_verifications",
        sa.Column("id", pg.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("project_id", pg.UUID(), sa.ForeignKey("public.projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", pg.UUID(), sa.ForeignKey("public.environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("status", sa.Text(), nullable=False), sa.Column("detail", sa.Text()), schema="blindspot")


def downgrade():
    op.execute("UPDATE blindspot.evidence SET captured_at = now() WHERE captured_at IS NULL")
    op.alter_column("evidence", "captured_at", nullable=False, server_default=sa.text("now()"), schema="blindspot")
    op.drop_table("environment_verifications", schema="blindspot")
    op.drop_table("import_requirements", schema="blindspot")
    op.drop_constraint("uq_imports_request_key", "imports", schema="blindspot")
    for name in ("warnings", "status", "fingerprint", "request_key"):
        op.drop_column("imports", name, schema="blindspot")
