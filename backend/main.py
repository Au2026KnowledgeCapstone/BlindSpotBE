from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from starlette.routing import Match
import os

from backend.auth import install_auth
from backend.feature_security import FEATURE_SECURITY

app = FastAPI(title="BlindSpot Backend")


class JSONBodyError(Exception):
    def __init__(self, status_code, title, description):
        self.status_code = status_code
        self.title = title
        self.description = description


@app.exception_handler(JSONBodyError)
async def json_body_error_handler(request: Request, exc: JSONBodyError):
    # Preserve Flask's existing malformed/missing JSON responses.
    return HTMLResponse(
        f"<!doctype html>\n<html lang=en>\n<title>{exc.status_code} {exc.title}</title>\n"
        f"<h1>{exc.title}</h1>\n<p>{exc.description}</p>\n",
        status_code=exc.status_code,
    )


async def parse_json_body(request: Request) -> Any:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not (media_type == "application/json" or
            (media_type.startswith("application/") and media_type.endswith("+json"))):
        raise JSONBodyError(415, "Unsupported Media Type",
                            "Did not attempt to load JSON data because the request Content-Type was not &#39;application/json&#39;.")
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        raise JSONBodyError(400, "Bad Request",
                            "The browser (or proxy) sent a request that this server could not understand.")


# Accept any JSON value, including null, without introducing schema validation.
JSONBody = Annotated[Any, Depends(parse_json_body)]
JSON_BODY_SCHEMA = {"requestBody": {"required": True, "content": {"application/json": {"schema": {}}}}}


@app.middleware("http")
async def automatic_options(request: Request, call_next):
    # Flask automatically registered OPTIONS for every endpoint.
    if request.method == "OPTIONS" and not request.url.path.startswith("/auth/"):
        methods = set()
        for route in app.routes:
            match, _ = route.matches(request.scope)
            if match != Match.NONE:
                methods.update(route.methods or [])
        if methods:
            return Response(headers={"Allow": ", ".join(sorted(methods | {"OPTIONS"}))})
    return await call_next(request)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL")
AI_API_KEY = os.getenv("AI_API_KEY")

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "API is running"}



## Creation
@app.post("/create-project", status_code=201, openapi_extra=JSON_BODY_SCHEMA, tags=["Projects"], **FEATURE_SECURITY)
def create_project(data: JSONBody):
    # Process the data and generate the create-project response
    response = {
        "message": "Project created successfully",
        "data_received": data
    }
    return response



## Reading
@app.post("/dashboard", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Dashboard"], deprecated=True, **FEATURE_SECURITY)
def dashboard(data: JSONBody):
    # Process the data and generate the dashboard response
    response = {
        "message": "Dashboard data processed successfully",
        "data_received": data
    }
    return response


@app.post("/accounts", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Accounts"], deprecated=True, **FEATURE_SECURITY)
def accounts(data: JSONBody):
    # Process the data and generate the accounts response
    response = {
        "message": "Accounts data processed successfully",
        "data_received": data
    }
    return response



@app.post("/environments", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Environments"], **FEATURE_SECURITY)
def environments(data: JSONBody):
    # Process the data and generate the environments response
    response = {
        "message": "Environments data processed successfully",
        "data_received": data
    }
    return response

@app.post("/projects/{project_name}", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Flows"], deprecated=True, **FEATURE_SECURITY)
def projects_names(project_name: str, data: JSONBody):
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name
    }
    return response


@app.post("/projects/{project_name}/flows/{flow_id}", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Flows"], deprecated=True, **FEATURE_SECURITY)
def projects_flows(project_name: str, flow_id: str, data: JSONBody):
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name,
        "flow_id": flow_id
    }
    return response



@app.post("/projects/{project_name}/run-test", status_code=200, openapi_extra=JSON_BODY_SCHEMA, tags=["Runs"], **FEATURE_SECURITY)
def run_test(project_name: str, data: JSONBody):
    # Process the data and generate the run-test response
    response = {
        "project_name": project_name,
        "status": 1,
    }


    ## VANSHIKA PLZ SEND REQUEST TO API URL HERE.

    request_data = {

    }



    return response



# API structure only. New handlers return 501 until their services are wired.
# Sessions/CSRF are enforced by FEATURE_SECURITY.
# TODO: Add authoritative project/environment/run ownership and membership policies.
# TODO: Validate JSON, filters, pagination cursors, and Idempotency-Key headers.
# Existing POST handlers remain placeholders; service integration is not implemented.


## Projects and environments
@app.get("/projects", status_code=501, tags=["Projects"], **FEATURE_SECURITY)
def list_projects():
    # TODO: Fetch the authenticated user's accessible projects and return a paginated list.
    # Query: limit, cursor. Only projects accessible to the authenticated user.
    response = {"items": [], "next_cursor": None}
    return response


@app.get("/environments", status_code=501, tags=["Environments"], **FEATURE_SECURITY)
def list_environments():
    # TODO: Check project access and fetch its environments with stable IDs and policies.
    # Required query: project_id. Optional: limit, cursor.
    response = {"items": [], "next_cursor": None}
    return response


@app.get("/environments/{environment_id}", status_code=501, tags=["Environments"], **FEATURE_SECURITY)
def environment_details(environment_id: str):
    # TODO: Load the authorized environment and its policy; return credential references only.
    response = {
        "id": environment_id,
        "project_id": None,
        "name": None,
        "kind": None,  # production, staging, pr_preview, development
        "base_url": None,
        "note": None,
        "credential_ref": None,  # Reference only; never return raw secrets.
        "execution_policy": None,
        "created_at": None,
    }
    return response


@app.get("/projects/{project_id}/credential-references", status_code=501, tags=["Projects"], **FEATURE_SECURITY)
def list_credential_references(project_id: str):
    # TODO: Fetch this project's authorized credential IDs/names without exposing secrets.
    # Item: id, name, kind. Never include secret values or storage locators.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return response


@app.get("/projects/{project_id}/execution-policies", status_code=501, tags=["Projects"], **FEATURE_SECURITY)
def list_execution_policies(project_id: str):
    # TODO: Fetch this project's policy revisions, allowed modes and execution limits.
    # Item: id, name, revision, allowed_execution_modes, execution limits.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return response


## Existing flow configuration (separate from executed results)
@app.get("/projects/{project_id}/flows", status_code=501, tags=["Flows"], **FEATURE_SECURITY)
def list_flows(project_id: str):
    # TODO: Fetch project flows with environment-scoped last-run status/time and recent history.
    # Required query: environment_id. Optional: limit, cursor.
    # Item: id, project_id, name, current_revision_id, runnable, last_run.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return response


@app.get("/projects/{project_id}/flows/{flow_id}", status_code=501, tags=["Flows"], **FEATURE_SECURITY)
def flow_details(project_id: str, flow_id: str):
    # TODO: Load configured flow steps/settings and recent runs for the selected environment.
    # Required query: environment_id. Recent runs are scoped to that environment.
    response = {
        "id": flow_id,
        "project_id": project_id,
        "name": None,
        "current_revision_id": None,
        "runnable": None,
        "configuration": {"steps": [], "settings": {}},
        "last_run": None,
        "recent_runs": [],
        "history_url": None,
    }
    return response


## Dashboard
@app.get("/dashboard", status_code=501, tags=["Dashboard"], **FEATURE_SECURITY)
def dashboard_summary(project_id: str | None = None, environment_id: str | None = None,
                      timezone: str = "UTC", as_of: str | None = None):
    # TODO: Calculate full-period metrics/costs/regressions and fetch the latest five runs separately.
    # Required query: project_id, environment_id. Optional: timezone, as_of.
    # Aggregate the full reporting period independently of latest_runs.
    response = {
        "project_id": project_id,
        "environment_id": environment_id,
        "timezone": timezone,
        "as_of": None,
        "execution_period": None,
        "total_execution_count": None,
        "terminal_execution_count": None,
        "pass_rate": {"passed_count": None, "denominator": None, "value": None},
        "weekly_ai_cost": {
            "amount": None, "currency": "USD", "status": "pending",
            "period_start": None, "period_end_exclusive": None,
            "pending_run_count": None, "unfinalized_run_count": None,
        },
        "trend": [],  # Seven local-calendar dates, including zero-activity days.
        "active_regression_count": None,
        "active_regressions": [],
        "active_regressions_next_cursor": None,
        "latest_runs": [],  # Latest five persisted runs, newest first.
        "latest_runs_next_cursor": None,
    }
    return response


# Shared route prefix. Ownership-chain validation remains unimplemented; no real resources are loaded.
RUN_PATH = "/projects/{project_id}/environments/{environment_id}/runs"


@app.get(RUN_PATH, status_code=501, tags=["Runs"], **FEATURE_SECURITY)
def list_runs(project_id: str, environment_id: str):
    # TODO: Query persisted runs with filters, newest-first ordering and cursor pagination (default five).
    # Query: limit (default 5), cursor, flow_id, status, created_from, created_to.
    # Order: created_at DESC, id DESC. Preserve older runs; cursor pagination.
    response = {
        "project_id": project_id, "environment_id": environment_id,
        "items": [], "next_cursor": None,
    }
    return response


@app.get(RUN_PATH + "/{run_id}", status_code=501, tags=["Runs"], **FEATURE_SECURITY)
def run_details(project_id: str, environment_id: str, run_id: str):
    # TODO: Load the actual run, saved configuration, cost and real passing/failing baseline references.
    response = {
        "id": run_id,
        "run_number": None,
        "project": {"id": project_id, "name": None},
        "environment": {"id": environment_id, "name": None, "kind": None},
        "flow": {"id": None, "name": None, "revision_id": None},
        "status": None,
        "branch": None,
        "commit_sha": None,
        "trigger": None,
        "created_at": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "action_count": None,
        "ai_cost": {"amount": None, "currency": "USD", "status": "pending"},
        "execution_mode": None,
        "pull_request": None,
        "primary_failure_id": None,
        "execution_snapshot": None,
        "rerun_of_run_id": None,
        "last_passing_run": None,
        "first_failing_run": None,
        "version": None,
        "last_event_id": None,
    }
    return response


@app.post(RUN_PATH + "/{run_id}/reruns", status_code=501, openapi_extra=JSON_BODY_SCHEMA, tags=["Runs"], **FEATURE_SECURITY)
def rerun_test(project_id: str, environment_id: str, run_id: str, data: JSONBody):
    # TODO: Validate source/access, allocate a new run number and atomically save/enqueue an idempotent rerun.
    # Body: {} or {"configuration_source": "latest_flow"}.
    # Default: original configuration. Require terminal source + Idempotency-Key.
    # Once implemented: return 202 with a NEW persisted run ID and run_number.
    response = {
        "project_id": project_id, "environment_id": environment_id,
        "rerun_of_run_id": run_id, "data_received": data,
        "id": None, "run_number": None, "status": None,
    }
    return response


## Executed steps, actions, failures and evidence
@app.get(RUN_PATH + "/{run_id}/steps", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def run_steps(project_id: str, environment_id: str, run_id: str):
    # TODO: Fetch this run's executed steps and results in execution order with pagination.
    # Query: limit, cursor. Ordered by position, id.
    # Item: id, run_id, configured_step_id, position, name, status, timestamps.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return response


@app.get(RUN_PATH + "/{run_id}/steps/{step_id}/actions", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def run_actions(project_id: str, environment_id: str, run_id: str, step_id: str):
    # TODO: Verify step ownership and fetch ordered actions with click metadata and screenshot links.
    # Query: limit, cursor. Ordered by run-wide action sequence.
    # Item includes status/times, click coordinates/viewport, before/after artifact IDs.
    response = {"run_id": run_id, "step_id": step_id, "items": [], "next_cursor": None}
    return response


@app.get(RUN_PATH + "/{run_id}/failures", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def run_failures(project_id: str, environment_id: str, run_id: str):
    # TODO: Load saved failure analysis, expected/observed results and linked evidence for this run.
    # Item: expected, observed, classification, likely_cause, suggested_next_steps,
    # analysis_status, evidence_artifact_ids and actual baseline run references.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return response


@app.get(RUN_PATH + "/{run_id}/artifacts", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def run_artifacts(project_id: str, environment_id: str, run_id: str):
    # TODO: Fetch authorized artifact metadata and step/action links; apply filters and pagination.
    # Query: type, step_id, action_id, limit, cursor.
    # Screenshots, before/after images, console/network logs and trace metadata.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return response


@app.post(RUN_PATH + "/{run_id}/artifacts/{artifact_id}/download", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def artifact_download(project_id: str, environment_id: str, run_id: str, artifact_id: str):
    # TODO: Verify artifact/run access and availability, then issue a five-minute signed download URL.
    # Authorize ownership, then issue a short-lived private object download URL.
    response = {"artifact_id": artifact_id, "url": None, "expires_at": None, "filename": None}
    return response


@app.get(RUN_PATH + "/{run_id}/logs", status_code=501, tags=["Run Evidence"], **FEATURE_SECURITY)
def run_logs(project_id: str, environment_id: str, run_id: str):
    # TODO: Fetch filtered, paginated console/network logs with redaction and response size limits.
    # Query: kind (console/network), artifact_id, level, from, to, limit, cursor.
    # Paginate redacted entries; do not embed large logs in run detail.
    response = {"run_id": run_id, "items": [], "next_cursor": None, "truncated": False}
    return response


@app.get(RUN_PATH + "/{run_id}/ai-usage", status_code=501, tags=["AI Usage"], **FEATURE_SECURITY)
def run_ai_usage(project_id: str, environment_id: str, run_id: str):
    # TODO: Fetch usage records and calculate the full run total with pending/partial/final cost state.
    # Query: limit, cursor. Total covers all run usage, not just this page.
    response = {
        "run_id": run_id, "items": [], "next_cursor": None,
        "total": {"amount": None, "currency": "USD", "status": "pending"},
    }
    return response


@app.get("/projects/{project_id}/environments/{environment_id}/regressions", status_code=501, tags=["Regressions"], **FEATURE_SECURITY)
def list_regressions(project_id: str, environment_id: str):
    # TODO: Fetch real environment regression records with baseline references and pagination.
    # Query: state (default active), limit, cursor. Return real failure metadata.
    response = {"items": [], "next_cursor": None}
    return response


## Run discussion
@app.get(RUN_PATH + "/{run_id}/comments", status_code=501, tags=["Run Discussion"], **FEATURE_SECURITY)
def list_run_comments(project_id: str, environment_id: str, run_id: str):
    # TODO: Fetch persisted run comments with author display names and timestamps in order.
    # Query: limit, cursor. Item: id, text, author {id, display_name}, created_at.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return response


@app.post(RUN_PATH + "/{run_id}/comments", status_code=501, openapi_extra=JSON_BODY_SCHEMA, tags=["Run Discussion"], **FEATURE_SECURITY)
def create_run_comment(project_id: str, environment_id: str, run_id: str, data: JSONBody):
    # TODO: Validate text/access and idempotently save a comment using the authenticated author.
    # Body: {"text": "..."}. Derive author from session; require Idempotency-Key.
    # Once persisted: return 201 with comment ID, author and timestamp.
    response = {"run_id": run_id, "data_received": data, "id": None, "author": None, "created_at": None}
    return response


## Notifications
@app.get("/notifications", status_code=501, tags=["Notifications"], **FEATURE_SECURITY)
def list_notifications():
    # TODO: Fetch this user's accessible notifications with read filters and pagination.
    # Query: read, project_id, environment_id, limit, cursor. Session recipient only.
    # Item: id, recipient_id, run_id/number, project/environment, type, title,
    # message, created_at, read_at. Completion retries must not duplicate rows.
    response = {"items": [], "next_cursor": None}
    return response


@app.get("/notifications/unread-count", status_code=501, tags=["Notifications"], **FEATURE_SECURITY)
def notification_unread_count():
    # TODO: Count all accessible unread notifications for the authenticated user and filters.
    # Optional query: project_id, environment_id. Count all accessible unread rows.
    response = {"unread_count": None}
    return response


@app.patch("/notifications/{notification_id}", status_code=501, openapi_extra=JSON_BODY_SCHEMA, tags=["Notifications"], **FEATURE_SECURITY)
def mark_notification_read(notification_id: str, data: JSONBody):
    # TODO: Verify recipient/access and persist the first read timestamp without changing it on retries.
    # Body: {"read": true}. Session recipient only; preserve first read timestamp.
    response = {"id": notification_id, "data_received": data, "read_at": None}
    return response


## Live updates (transport not implemented)
@app.get(RUN_PATH + "/{run_id}/events", status_code=501, tags=["Live Updates"], **FEATURE_SECURITY)
def run_events(project_id: str, environment_id: str, run_id: str):
    # TODO: text/event-stream with durable per-run IDs and Last-Event-ID/after.
    # Events: run/step/action, screenshot, analysis, completion, usage/artifacts.
    # Persist before publish; replay ordered events; FE deduplicates and refetches.
    response = {"message": "Run event streaming is not implemented", "run_id": run_id}
    return response


@app.get("/events", status_code=501, tags=["Live Updates"], **FEATURE_SECURITY)
def user_events():
    # TODO: Authenticated user SSE for notification.created/read, run.updated,
    # dashboard.invalidated. Support reconnect/resume and membership changes.
    response = {"message": "User event streaming is not implemented"}
    return response


## Internal service callbacks (separate service authentication required)
@app.post("/internal/v1/runs/{run_id}/execution-events", status_code=501, tags=["Internal Callbacks"])
def receive_execution_event(run_id: str):
    # TODO: Authenticate the worker/job, deduplicate/order events, save results and publish durable updates.
    # Body: event_id, job_id, attempt, sequence, type, occurred_at,
    # schema_version, payload. Deduplicate and validate job/run binding.
    # Do not accept events or echo potentially sensitive executor payloads yet.
    response = {"message": "Execution event ingestion is not implemented", "run_id": run_id}
    return response


@app.post("/internal/v1/runs/{run_id}/ai-usage", status_code=501, tags=["Internal Callbacks"])
def receive_ai_usage(run_id: str):
    # TODO: Authenticate the service and persist usage revisions idempotently; update costs and notify FE.
    # Body: usage_id, event_id, revision, cost_session_id, job_id, attempt,
    # provider, model, operation, tokens, amount, currency, status, timestamps.
    # AI service must durably save usage before delivery. Idempotent BE upsert.
    response = {"message": "AI usage ingestion is not implemented", "run_id": run_id}
    return response


@app.post("/internal/v1/runs/{run_id}/ai-cost-finalizations", status_code=501, tags=["Internal Callbacks"])
def finalize_ai_cost(run_id: str):
    # TODO: Authenticate the service and verify all expected final usage before saving final cost state.
    # Body: event_id, cost_session_id, revision, final_usage_count/digest, closed_at.
    # Finalize only after all final usage matches; completion alone is insufficient.
    response = {"message": "AI cost finalization is not implemented", "run_id": run_id}
    return response


install_auth(app)


# Preserve Flask's automatic HEAD support without adding duplicate OpenAPI operations.
for route in list(app.routes):
    if getattr(route, "path", None) and "GET" in (getattr(route, "methods", None) or set()):
        if "HEAD" not in route.methods:
            app.add_api_route(route.path, route.endpoint, methods=["HEAD"],
                              status_code=route.status_code, dependencies=route.dependencies,
                              include_in_schema=False)


# Register every route before starting the development server.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0",
                port=int(os.getenv("PORT", "8000")))
