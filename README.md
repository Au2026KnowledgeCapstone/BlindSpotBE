# BlindSpot Backend

Initialize the Python environment and install dependencies:

```bash
make initialize
```

Start the Flask development server at http://127.0.0.1:5000:

```bash
make run
```

To use the environment in your shell:

```bash
source .venv/bin/activate
```

## Cloud Run continuous deployment (Google Cloud Buildpacks)

Build from the repository root, where `requirements.txt`, `.python-version`
and `Procfile` live. Python 3.12 is selected by `.python-version`; Gunicorn
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
python3.12 -m venv /tmp/blindspotbe-check
/tmp/blindspotbe-check/bin/python -m pip install -r requirements.txt
export PORT=8080
/tmp/blindspotbe-check/bin/gunicorn --bind 0.0.0.0:$PORT --access-logfile - --error-logfile - backend.main:app
# In another terminal: curl --fail http://127.0.0.1:8080/
```

In the existing GitHub trigger, keep the build context at the repository root
and the build method set to Google Cloud Buildpacks. Any existing build-time
`GOOGLE_ENTRYPOINT` or `GOOGLE_PYTHON_VERSION` overrides must be removed or
aligned with the command above and Python `3.12.x`. Leave Cloud Run container
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
