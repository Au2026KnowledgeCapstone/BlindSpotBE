"""B1 Step 6. Round-trips against local Postgres, not SQLite: several
blindspot columns are JSONB, which SQLite cannot represent — these tests
need the real dialect.

The two tests that touch the live Supabase project skip when
SUPABASE_DATABASE_URL isn't configured, so the suite stays green without
that secret (e.g. in an environment that only has local Postgres)."""
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def _supabase_database_url() -> str | None:
    return os.environ.get("SUPABASE_DATABASE_URL") or dotenv_values(REPO_ROOT / ".env").get(
        "SUPABASE_DATABASE_URL"
    )


def _alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


def _connect_or_skip(url: str):
    """Supabase's direct-connection host is IPv6-only; some environments
    (including this one, intermittently) have no IPv6 egress. That's a
    reachability problem, not a correctness one — skip rather than fail."""
    engine = create_engine(url)
    try:
        conn = engine.connect()
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"Supabase unreachable from this environment: {exc}")
    conn.close()
    return engine


@pytest.fixture
def local_engine():
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        # Alembic doesn't create its own target schema; these FK targets
        # don't exist on a bare local Postgres the way they do on Supabase.
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS blindspot"))
        from app.models import Project, Environment
        Project.__table__.create(conn, checkfirst=True)
        Environment.__table__.create(conn, checkfirst=True)
    yield engine
    engine.dispose()


def test_upgrade_downgrade_round_trip(local_engine):
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    with local_engine.connect() as conn:
        tables = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'blindspot'")
        ).scalars().all()
    assert "requirements" in tables
    assert "results" in tables
    assert "alembic_version" in tables


def test_composite_fk_tenancy_rejects_mismatched_project(local_engine):
    command.upgrade(_alembic_config(), "head")

    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    environment_id = uuid.uuid4()
    run_id = uuid.uuid4()
    requirement_id = uuid.uuid4()

    with pytest.raises(IntegrityError, match="fk_results_analysis_run_tenancy"):
        with local_engine.connect() as conn, conn.begin():
            conn.execute(
                text("INSERT INTO public.projects (id, owner_id, name, description, created_at) VALUES (:a, gen_random_uuid(), 'A', '', now()), (:b, gen_random_uuid(), 'B', '', now())"),
                {"a": project_a, "b": project_b},
            )
            conn.execute(text("INSERT INTO public.environments (id, project_id, name, kind, base_url, revision, created_at) VALUES (:e, :p, 'Staging', 'staging', 'https://example.com', 1, now())"), {"e": environment_id, "p": project_a})
            conn.execute(
                text(
                    "INSERT INTO blindspot.analysis_runs "
                    "(id, project_id, environment_id, run_number, engine, status, "
                    " requirement_snapshots, requested_by, queued_at) "
                    "VALUES (:id, :project_id, :environment_id, 1, 'mvp', 'queued', "
                    " '[]'::jsonb, gen_random_uuid(), now())"
                ),
                {"id": run_id, "project_id": project_a, "environment_id": environment_id},
            )
            conn.execute(
                text("INSERT INTO blindspot.requirements (id, project_id, title) VALUES (:id, :project_id, 'x')"),
                {"id": requirement_id, "project_id": project_b},
            )
            # project_b disagrees with the run's actual project (project_a) —
            # the database, not application code, must reject this.
            conn.execute(
                text(
                    "INSERT INTO blindspot.results "
                    "(id, project_id, analysis_run_id, requirement_id, verdict, classification, "
                    " observed_behavior, duration_ms) "
                    "VALUES (gen_random_uuid(), :project_id, :run_id, :requirement_id, "
                    " 'pass', 'criteria_satisfied', 'x', 1)"
                ),
                {"project_id": project_b, "run_id": run_id, "requirement_id": requirement_id},
            )


def test_autogenerate_against_live_schema_is_empty(monkeypatch):
    """Regression test for the include_object filter in migrations/env.py —
    the single most important line in B1 Step 3."""
    supabase_url = _supabase_database_url()
    if not supabase_url:
        pytest.skip("SUPABASE_DATABASE_URL not configured")

    _connect_or_skip(supabase_url).dispose()

    monkeypatch.setenv("DATABASE_URL", supabase_url)
    get_settings.cache_clear()
    script = None
    try:
        script = command.revision(_alembic_config(), message="pytest_zero_diff_check", autogenerate=True)
        body = Path(script.path).read_text()
        assert body.count("    op.") == 0, body
    finally:
        if script is not None:
            Path(script.path).unlink(missing_ok=True)
        get_settings.cache_clear()


def test_anon_and_authenticated_have_no_blindspot_privileges():
    supabase_url = _supabase_database_url()
    if not supabase_url:
        pytest.skip("SUPABASE_DATABASE_URL not configured")

    engine = _connect_or_skip(supabase_url)
    try:
        with engine.connect() as conn:
            grants = conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'blindspot' AND grantee IN ('anon', 'authenticated')"
                )
            ).all()
            assert grants == []

            usage = conn.execute(
                text(
                    "SELECT has_schema_privilege('anon', 'blindspot', 'USAGE') AS anon_usage, "
                    "has_schema_privilege('authenticated', 'blindspot', 'USAGE') AS authenticated_usage"
                )
            ).one()
            assert usage.anon_usage is False
            assert usage.authenticated_usage is False
    finally:
        engine.dispose()


def test_local_schema_matches_models(local_engine):
    command.upgrade(_alembic_config(), "head")
    command.check(_alembic_config())
