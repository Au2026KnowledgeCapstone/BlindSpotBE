# BlindSpot Backend

Initialize the Python environment and install dependencies:

```bash
make initialize
```

Start the FastAPI development server at http://localhost:8000:

```bash
make run
```

To use the environment in your shell:

```bash
source .venv/bin/activate
```

## Cloud Run continuous deployment (Google Cloud Buildpacks)

Build from the repository root, where `requirements.txt`, `.python-version`
and `Procfile` live. Python 3.13 is selected by `.python-version`; Uvicorn
imports the FastAPI application as `backend.main:app`.

Production command (run from the repository root):

```bash
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-5000}
```

Cloud Run supplies `PORT` automatically. The backend reads `AI_SERVICE_URL` and
`AI_API_KEY` from the runtime environment. Configure these for the intended AI
service integration (store the API key as a secret); the current placeholder
handlers do not use them and they are not required for startup. The existing `GET /` endpoint
returns HTTP 200 with `{"status":"ok","message":"API is running"}` and can be
used for health checks. Local development still uses `make run`.

For a clean local production smoke test:

```bash
python3.13 -m venv /tmp/blindspotbe-check
/tmp/blindspotbe-check/bin/python -m pip install -r requirements.txt
export PORT=8080
/tmp/blindspotbe-check/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-5000}
# In another terminal: curl --fail http://localhost:8080/
```

In the existing GitHub trigger, keep the build context at the repository root
and the build method set to Google Cloud Buildpacks. Any existing build-time
`GOOGLE_ENTRYPOINT` or `GOOGLE_PYTHON_VERSION` overrides must be removed or
aligned with the command above and Python `3.13.x`. Leave Cloud Run container
command/argument overrides empty so the generated image entrypoint is used.
`app.yaml` is an App Engine configuration and is not used by this deployment.
This Python backend needs no `package.json`; do not include the local Node
startup experiment referencing `server.js` in the deployment commit.

Interactive API documentation is available at http://localhost:8000/docs;
the OpenAPI schema is at http://localhost:8000/openapi.json.

Supabase cookie authentication is available under `/auth` (see below). Existing
feature placeholder responses, including HTTP 501 responses, remain unchanged.
Role authorization, database operations, AI service calls, and event streaming
are not implemented. All 33 feature operations now require verified backend
sessions (and CSRF on mutations); project-level authorization remains pending.
Internal callbacks remain nonfunctional 501 stubs pending separate service auth.

## Application URLs and Swagger groups

Application routes now omit the leading `/api` prefix: for example,
`/api/projects` becomes `/projects`. Existing clients using `/api/...` URLs
must update; no compatibility aliases are provided. `/internal/v1` callbacks
and framework documentation URLs remain unchanged.

Swagger uses separate Projects and Environments groups, plus Health, Dashboard,
Accounts, Flows, Runs, Run Evidence, AI Usage, Regressions, Run Discussion,
Notifications, Live Updates, and Internal Callbacks.

Only POST `/dashboard`, POST `/accounts`, POST `/projects/{project_name}`, and
POST `/projects/{project_name}/flows/{flow_id}` are deprecated in OpenAPI.
All four remain visible and callable. All 37 application operations retain their
methods, response bodies, and status codes, including placeholder 501 responses.
See [the API reference](docs/frontend-api-design.md) for intended behavior.

Run the route contract tests from the repository root:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

## Supabase authentication

See [authentication setup, API contract, CSRF protocol, and local login test](docs/authentication.md).
Use the existing frontend Supabase project, configure the gitignored `.env` from
`.env.example`, and use localhost for both apps: frontend port 3000, backend port
8000. `make run` now uses localhost:8000. No service-role key is needed.

The nine `/auth` operations use the Authentication Swagger group. Access/refresh
tokens are stored only in HttpOnly cookies; auth JSON never returns them. Auth
API POSTs require an allowed Origin, JSON, and `X-CSRF-Protection: 1`. Frontend
requests must use `credentials: "include"`. All 37 original operations remain
present, for 46 application operations total. The frontend now uses backend
signup, confirmation and recovery too, using backend-owned PKCE. Keep shared
email templates unchanged; add the callback allowlist patterns documented in
the authentication guide and configure AUTH_FLOW_ENCRYPTION_KEY. Workspace
SDK/data access remains separate.

## Feature endpoint security

All 33 user-facing feature operations, including legacy placeholders and generated
HEAD routes, now require the Supabase-verified backend session. Mutations require
an allowed Origin, application/json and X-CSRF-Protection:1. Bodies/statuses remain
unchanged after those checks; unimplemented operations stay unimplemented.
See [the full route/security inventory](docs/endpoint-security.md) for public and
auth routes, the three disabled internal callbacks, and missing authoritative
project membership/policy decisions. Being signed in is not project authorization.
