# BlindSpot Backend

FastAPI service. Every route is declared in `main.py` at the repo root;
handlers stay thin and delegate to `app/services/`.

## Local development

Install the project and its test extras from `pyproject.toml`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

`requirements-dev.txt` is a compatibility entry for editable `.[test]`; the
optional test extra includes pytest, pytest-asyncio, and `psycopg[binary]`.

Start the development server at http://127.0.0.1:8000:

```bash
make run
```

To use the environment directly in your shell:

```bash
source .venv/bin/activate
```

Run the full test suite against the isolated local PostgreSQL/PostgREST
fixtures (the integration tests create and drop disposable databases):

```bash
export POSTGRES_TEST_ROOT=/home/nala/quoroum-backend/data/ops/mohagany-test-postgres
export POSTGREST_BIN=/home/nala/quoroum-backend/data/ops/mohagany-reviewed-capstone/postgrest
export DATABASE_URL='postgresql+psycopg://nala@/postgres?host=/home/nala/quoroum-backend/data/ops/mohagany-test-postgres/socket&port=55432'
.venv/bin/python -m pytest -q
```

The local PostgreSQL instance must be running with the test-only bootstrap
support installed; PostgREST must be available at `POSTGREST_BIN`. The database
and PostgREST integration tests create and drop disposable databases. Never
point `DATABASE_URL` or `SUPABASE_DATABASE_URL` at production. The inherited B1
migration tests require a separate disposable PostgreSQL database configured in
`DATABASE_URL` and run Alembic against that local database; keep them separate
from the auth, workspace API, and infrastructure integration checks above.

## Layout

```
BlindSpotBE/
├── main.py              # every route, at the repo root
├── app/
│   ├── core/             # config, db session, logging, auth
│   ├── services/         # all business logic
│   ├── models/           # SQLAlchemy models + Alembic
│   └── schemas/          # Pydantic request/response models
├── tests/
├── docs/
└── pyproject.toml
```

## Configuration

Copy `.env.example` to `.env` and fill in values for local development. Never
commit `.env` or any real secrets.

## Authentication

BE owns the full login/session lifecycle — the frontend never holds a token
or talks to Supabase directly; BE issues httpOnly cookies and verifies every
one of them against Supabase. There is no local dev bypass: local dev needs
a real Supabase project and a real login through `/auth/login`. See
`docs/authentication.md` for setup and the full flow.


## API Reference
The API is fully typed and documented. Run the server and visit `/docs` for
the OpenAPI spec and interactive Swagger UI. Visit `/redoc` for ReDoc.

http://localhost:8000/docs#/

## AI integration

Requirements, environments, runs, durable job dispatch, callback ingestion,
usage reconciliation and replayable run events are implemented. Start the
separate dispatcher alongside the API:

```bash
.venv/bin/python -m app.services.dispatch
```

See [AI integration](docs/ai-integration.md) for configuration, testing,
operational recovery, and remaining executor capabilities (document extraction,
login verification, private evidence storage and remote cancellation).
