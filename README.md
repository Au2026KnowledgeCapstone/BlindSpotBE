# BlindSpot Backend

Initialize the Python environment and install dependencies:

```bash
make initialize
```

Start the Flask development server at http://127.0.0.1:8000:

```bash
make run
```

To use the environment in your shell:

```bash
source .venv/bin/activate
```

## Swagger API documentation

After `make run`, open http://127.0.0.1:8000/docs for Swagger UI and **Try it out**.
The local server defaults to port 8000 to avoid macOS AirPlay using port 5000.
Use `PORT=8080 make run` to choose another port. `make run` initializes the
environment automatically if it is missing.

The OpenAPI 3.0 document is served at `/openapi.json` and maintained in
[`docs/openapi.json`](docs/openapi.json). It covers all 37 application operations,
including legacy POST handlers and internal service callbacks. The UI uses the
current backend origin, so the same links work after deployment.

The documentation describes current placeholder responses: newer handlers return
HTTP 501, while legacy handlers echo data or return placeholder success. Planned
query parameters and headers are labeled accordingly; authentication and SSE are
not implemented. See [the intended API contracts](docs/frontend-api-design.md).
Legacy `project_name` POST paths share an OpenAPI `project_id` path parameter with
equivalent GET paths; those POST handlers still interpret it as a project name.

Swagger UI loads pinned JavaScript/CSS from unpkg and requires internet access.
Its setup follows the [official Swagger UI installation guide](https://swagger.io/docs/open-source-tools/swagger-ui/usage/installation/).
Update the specification when changing handlers. Run `python -m unittest discover -s tests -v`
to check route coverage and current response examples alongside CORS behavior.

## Cloud Run frontend connection

- Backend: https://blindspotbe-git-158196513287.europe-west1.run.app
- Frontend: https://blindspotfe-158196513287.europe-west1.run.app

Set `CORS_ALLOWED_ORIGINS` on the backend to the exact frontend origin above
(no trailing slash). Comma-separate additional origins when needed. An empty
setting grants no browser CORS access. CORS does not validate Supabase users;
authentication and project ownership still need implementation.

Set `NEXT_PUBLIC_API_BASE_URL` to the backend URL **during the frontend build**,
then rebuild/redeploy the frontend. Runtime-only changes do not update a
Next.js browser bundle. The frontend has a read-only `/dev/integration` page:
click **Run connection checks** to test real browser requests and preflight.
Health should pass; projects currently reports HTTP 501 because it is a stub.
This verifies connectivity, not completed application-data/auth integration.

Run backend CORS checks locally:

```bash
python -m unittest discover -s tests -v
```

## Cloud Run continuous deployment (Google Cloud Buildpacks)

Build from the repository root, where `requirements.txt`, `.python-version`
and `Procfile` live. Python 3.13 is selected by `.python-version`; Gunicorn
imports the existing Flask application as `backend.main:app`.

Production command (run from the repository root):

```bash
gunicorn --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - backend.main:app
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
/tmp/blindspotbe-check/bin/gunicorn --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - backend.main:app
# In another terminal: curl --fail http://127.0.0.1:8080/
```

In the existing GitHub trigger, keep the build context at the repository root
and the build method set to Google Cloud Buildpacks. Any existing build-time
`GOOGLE_ENTRYPOINT` or `GOOGLE_PYTHON_VERSION` overrides must be removed or
aligned with the command above and Python `3.13.x`. Leave Cloud Run container
command/argument overrides empty so the generated image entrypoint is used.
`app.yaml` is an App Engine configuration and is not used by this deployment.
This Python backend needs no `package.json`; do not include the local Node
startup experiment referencing `server.js` in the deployment commit.

Commit only the relevant deployment files, then push the branch configured in
the existing GitHub trigger:

```bash
git add Procfile .python-version requirements.txt .gitignore README.md
git diff --cached
git commit -m "Configure Python buildpack startup for Cloud Run"
git push origin HEAD
```

Verify the current branch matches the trigger branch before pushing. No Dockerfile
or additional Cloud Build workflow is required. Never commit `.env` files or
credentials; configure any future secrets through Cloud Run's runtime settings.
