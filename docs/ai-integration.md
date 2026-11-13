# Backend / aiservice integration

This implementation starts from `origin/main` at `9ec4c56` (FastAPI), rather
than the older Flask checkout. Existing cookie sessions, CSRF protection,
Supabase workspace APIs, project membership checks, and private `blindspot`
schema ownership remain the foundation.

## What was missing and what is implemented

| Area | Implemented behavior |
| --- | --- |
| Requirements | Project-scoped CRUD, criterion identity reconciliation, search/filter/pagination, explicit approval, latest result |
| Approval | Editing content resets draft; empty criteria and unresolved clarification cannot be approved |
| Environments | Read/list/update, encrypted write-only credentials, revision and verification invalidation |
| Runs | Approved selections, maximum ten, project-locked numbering, frozen criteria/target/credential snapshots, run/result/usage reads |
| Submission retries | Optional `Idempotency-Key`, scoped to project/environment/user; conflicting reuse is 409; omitted keys create new runs |
| Dispatch | Run and encrypted dispatch committed together; separate leased worker; stable job ID and immutable envelope across retries |
| Execution callbacks | Job-scoped token authentication, run/job binding, stable event-ID deduplication, increasing sequences, terminal-state protection |
| Results | Snapshot-bound per-requirement outcomes, criterion source/rationale/citations, actions; no invented pass verdicts |
| Metering | Latest usage revision replaces prior revision; exact 12-place decimals; reserved usage is not billed |
| Cost closure | Count AND SHA-256 digest checked; missing data is retryable 503; unknown amounts stay null |
| Live updates | Durable per-run inbox positions, SSE replay with Last-Event-ID or after; membership rechecked while connected |
| Notifications | One notification for terminal execution or permanent dispatch failure; replay creates no duplicate |
| Cancellation | Safe before any dispatch attempt; already attempted work returns 409 because executor cancellation is unavailable |

The v2 reference supplied requirement approval/reset behavior, project-scoped
resource handling, frozen approved requirements, run/result separation, and
unknown usage semantics. Its embedded browser workers and direct AI SDK calls
were deliberately kept behind the independent aiservice HTTP boundary. No
models, imports, or database connection from aiservice are used by this backend.

## Configure and run

Use `.env.example` and configure the existing Supabase authentication and BE
PostgreSQL connection first. Apply the existing Supabase public migrations
through your normal deployment workflow; Alembic only owns `blindspot`.

Set `AI_SERVICE_URL` to aiservice's origin and `AI_API_KEY` to its
`SERVICE_TOKEN`. Set `AI_CALLBACK_BASE_URL` to a BE URL reachable from the
executor, ending in `/internal/v1`. Container deployments need resolvable
service hostnames. Use HTTPS for service traffic in deployment.

Generate **separate, persistent** Fernet keys for `DISPATCH_ENCRYPTION_KEY`
and `ENVIRONMENT_CREDENTIAL_ENCRYPTION_KEY`. Dispatch envelopes include the
job callback token and immutable environment credentials, encrypted at rest.
Keep these keys in your existing secret manager. Never rotate them without
re-encrypting pending envelopes/credentials.

```bash
.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Run the durable dispatcher as a **separate process** with the same BE settings:

```bash
.venv/bin/python -m app.services.dispatch
# One eligible delivery, useful for diagnostics:
.venv/bin/python -m app.services.dispatch --once
```

Configure aiservice's own database, migrate it, set `ENGINE=stub`, and run it
according to that repository's README. `AI_ENGINE=stub` is the backend default
because aiservice's mvp/graph adapters are not implemented. Stub verdicts are
inconclusive; the passing integration test does not demonstrate browser parity.

Authenticated product requests use existing cookies and CSRF headers:

```text
POST /projects/{pid}/environments/{eid}/runs
Origin: <configured frontend origin>
X-CSRF-Protection: 1
Idempotency-Key: <one stable key per intended run>
Content-Type: application/json

{"requirement_ids": ["<approved requirement UUID>"]}
```

The response is 202 only after run and dispatch persistence. It does not mean
the executor has accepted the job yet. Runs list newest first, with an opaque
run-number cursor. Result duration is null when the executor has not measured
it. The run response includes full immutable requirement criteria.

## Callback and retry rules

The three endpoints match `aiservice/app/callbacks/schemas.py`:

* `/internal/v1/runs/{id}/execution-events`
* `/internal/v1/runs/{id}/ai-usage`
* `/internal/v1/runs/{id}/ai-cost-finalizations`

Supply `Authorization: Bearer <job callback_token>`. The intake service token
cannot authenticate a callback. A valid identical replay returns 202, including
a replay after terminal execution or cost closure. Reusing an event ID with a
changed body returns 409. Execution sequences may have gaps occupied by usage
messages. BE assigns a separate monotonic inbox position for all callback kinds
so usage and finalization can also be replayed through SSE.

A run lock serializes callback changes and their inbox records in the same
transaction. An execution completion requires all selected outcomes. Provider
usage can arrive after execution is terminal; only a verified cost closure
sets cost final/unknown. Zero requests plus a matching empty digest is a known
zero. Unknown provider charges are never replaced with zero.

Dispatch uses `FOR UPDATE SKIP LOCKED`, a lease, and conditional lease-owner
acknowledgment. Network errors, 408/429, and 5xx retry with capped exponential
backoff. Other HTTP responses are permanent failures and mark a still-queued
run failed. An expired lease can send the same envelope again; aiservice's
stable job ID deduplicates execution. A malformed 202 acknowledgment retries.

Monitor `blindspot.dispatches` for pending age, attempts, `last_error`, and
expired leases. `last_error` stores a category, never response bodies/secrets.
After correcting a permanent configuration/auth problem, an operator can reset
that exact dispatch to pending and its run to queued in a controlled database
transaction; preserve job ID, envelope and event history. There is no automatic
operator replay endpoint or key-rotation UI.

## Remaining upstream capabilities

These endpoints continue to return explicit 501 responses because the current
executor has no supporting protocol. This branch does not fabricate success:

* Document import/extraction and retained source-document download: v2's AI
  extraction runs in-process; aiservice only exposes jobs, not an import API.
  An extraction contract and private document storage must be implemented next.
* Environment login verification: requires a real browser engine and a typed
  verification result, not a stub execution.
* Evidence retrieval: A1 evidence IDs name operational outbox records, not
  uploaded private objects. A2 must provide authorized storage references and
  an upload/retrieval contract before BE can issue signed downloads.
* Remote cancellation: aiservice has no cancellation endpoint. Only a job that
  BE has never attempted to send can currently be cancelled safely.

Callback result JSON retains citations and action evidence IDs without creating
fake downloadable evidence records. Source requirements with results cannot be
deleted because history references them; active selected requirements are also
protected. Engine cost/pricing implementations and live browser behavior remain
executor work, not BE behavior proven by these tests.

## Verification

Use a **disposable** local database ending in `_integration`. Never use a shared
or production database: existing migration tests perform downgrade/upgrade.

```bash
export BLINDSPOT_TEST_DATABASE_URL='postgresql+psycopg2://USER@127.0.0.1:PORT/blindspot_integration'
export DATABASE_URL="$BLINDSPOT_TEST_DATABASE_URL"
.venv/bin/python -m tools.bootstrap_integration_db
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest -q
```

The bootstrap creates only test copies of public model tables. It is not a
replacement for the real Supabase migrations. Infrastructure/PostgREST and live
Supabase privilege tests require their separately documented opt-in settings.

For the real two-service HTTP test, add:

```bash
export AISERVICE_REPO='/absolute/path/to/aiservice'
# Optional if its interpreter is elsewhere:
export AISERVICE_PYTHON="$AISERVICE_REPO/.venv/bin/python"
.venv/bin/python -m pytest tests/test_executor_round_trip.py -q
```

This launches actual BE and executor HTTP servers on temporary local ports,
uses an independent temporary SQLite executor database and the disposable BE
PostgreSQL database, dispatches through the real intake, and checks durable
results and verified cost closure. No real model, external target navigation,
cloud upload, or production database is used.

Recorded verification on 2026-11-13: **78 tests passed, 25 subtests passed,
15 skipped** using PostgreSQL 14 and Python 3.14. The skipped checks require
PostgREST/infrastructure fixtures, live Supabase privileges, or the external API
draft. One existing Starlette/httpx deprecation warning remains. Alembic
upgrade/downgrade/upgrade and `alembic check` pass with no model/schema drift.
The schema check also covers a database role named `blindspot`: migrations use
an explicit search path so PostgreSQL's implicit `$user` schema and public FK
reflection do not generate false changes.

Sources reviewed: BE baseline `9ec4c56`, local aiservice `5222a8f`, local v2
`47ca7ee`. The executor and v2 repositories were read and used for the round-trip
verification; neither repository was modified.
