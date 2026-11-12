# Reproduce API and infrastructure checks

Use only the isolated local PostgreSQL cluster. Never set `SUPABASE_DATABASE_URL` or point `DATABASE_URL` at a hosted database. Integration tests create disposable uniquely named databases and use synthetic identities.

## API/auth contract tests

Install the declared extras in a fresh environment:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Run cookie/auth and canonical API contract tests without a database or real Supabase credentials:

```bash
unset SUPABASE_DATABASE_URL
.venv/bin/python -m pytest -q tests/test_auth.py tests/test_api_surface.py tests/test_workspace_api.py
```

These tests use FastAPI's actual auth dependencies with mocked Supabase/PostgREST transports. They never print tokens or use a service-role key.

## PostgreSQL/PostgREST tests

Configure the isolated PostgreSQL fixture explicitly. `BLINDSPOT_TEST_PGHOST`, `BLINDSPOT_TEST_PGPORT`, and `BLINDSPOT_TEST_PGUSER` default to `localhost`, `5432`, and the current OS user; `BLINDSPOT_TEST_PGPASSWORD` is optional. These settings are test-only and never read `.env`, `DATABASE_URL`, or `SUPABASE_DATABASE_URL`. If the local PostgreSQL endpoint is unavailable, infrastructure tests skip with the required variable names. The configured role must be authorized to create/drop disposable databases and test-only roles. Do not alter cluster-global roles as part of a test.

Example for the supplied isolated Quorum fixture:

```bash
mkdir -p .tools
export BLINDSPOT_TEST_PGHOST=/home/nala/quoroum-backend/data/ops/mohagany-test-postgres/socket
export BLINDSPOT_TEST_PGPORT=55432
export BLINDSPOT_TEST_PGUSER=nala
export POSTGREST_BIN=/home/nala/quoroum-backend/data/ops/mohagany-reviewed-capstone/postgrest
unset SUPABASE_DATABASE_URL DATABASE_URL
.venv/bin/python -m pytest -q tests/infrastructure
```

Each test run creates a random disposable database, closes fixture connections before dropping it, and force-cleans it on fixture setup failures. PostgREST v16.5 is downloaded from its official release and its published SHA256 is checked before use; override `POSTGREST_BIN` to use an existing binary.

B1 migration round-trip tests require their own clean local database URL; run separately from the RLS/PostgREST fixture, because the B1 fixture creates only minimal public `projects` and `environments` tables. The tests that read `.env` for `SUPABASE_DATABASE_URL` must run with that variable unset and with any inherited real `.env` fallback removed/disabled in the disposable test copy. Do not run live-schema migration/autogenerate tests against hosted Supabase.

## Migration ownership and rollout

`app/models/migrations` / Alembic owns the `blindspot` schema only. Its current deployed head was verified read-only as `f11ed461fc25`. `blindspot.analysis_runs`, `imports`, `requirements`, and `ai_usage` have foreign keys into the existing `public.projects`/`public.environments`; never recreate, move, or drop public tenancy. `public.environments` also has team-managed `encrypted_credentials`, `revision`, and `verified_at`; `application_id` is nullable. Retain existing rows/columns and never return encrypted credential values. Set `ENVIRONMENT_CREDENTIAL_ENCRYPTION_KEY` to a valid Fernet key when accepting environment credentials; generate one with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` and store it in the deployment secret manager. Do not rotate without a decrypt/re-encrypt plan.

Public tenancy changes are Supabase SQL migrations, not Alembic. The existing `20261026231753_application_infrastructure` baseline is already represented in the hosted schema; do not replay that baseline against it. `20261105000100_customer_organizations.sql` added an organizations layer as an additive follow-up; `20261111180000_remove_organizations.sql` is a reviewed, deliberate follow-up that removes it entirely — organizations never grew real management functionality (no rename/delete, no org-level member management, no settings), and the removal was an explicit product decision, applied to the hosted database. `can_access`/`can_manage` are back to their pre-organization, project-members-only form. Before any further schema change, verify the Supabase migration ledger and exact public catalog against the baseline; if ledger history is missing but schema is already present, use the reviewed Supabase migration-repair workflow after independent catalog review. Apply new migrations in a disposable clean Supabase-compatible database first; validate RLS, RPC grants, and blindspot FK continuity.

## Frontend checks

From the isolated BlindSpotFE review worktree (Node version supported by its lockfile):

```bash
npm ci
npm run typecheck
npx eslint src/features/workspace src/app/workspace src/app/projects/page.tsx
npm test
npm run build
```

The browser check should use a synthetic identity with all Data API requests routed to the local PostgREST/PostgreSQL fixture. It does not validate hosted login or deployment.
