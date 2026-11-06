# BlindSpot Backend

FastAPI service. Every route is declared in `main.py` at the repo root;
handlers stay thin and delegate to `app/services/`.

## Local development

Install dependencies (editable install, including test extras):

```bash
make initialize
```

Start the development server at http://127.0.0.1:8000:

```bash
make run
```

To use the environment directly in your shell:

```bash
source .venv/bin/activate
```

Run the test suite:

```bash
pytest -q
```

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
    