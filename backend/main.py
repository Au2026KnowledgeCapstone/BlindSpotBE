from flask import Flask, jsonify, request
import os

app = Flask(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL")
AI_API_KEY = os.getenv("AI_API_KEY")

@app.get("/")
def health_check():
    return jsonify({"status": "ok", "message": "API is running"})



## Creation    
@app.route("/api/create-project", methods=["POST"])
def create_project():
    data = request.get_json()
    # Process the data and generate the create-project response
    response = {
        "message": "Project created successfully",
        "data_received": data
    }
    return jsonify(response), 201



## Reading
@app.route("/api/dashboard", methods=["POST"])
def dashboard():
    data = request.get_json()
    # Process the data and generate the dashboard response
    response = {
        "message": "Dashboard data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200


@app.route("/api/accounts", methods=["POST"])
def accounts():
    data = request.get_json()
    # Process the data and generate the accounts response
    response = {
        "message": "Accounts data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200



@app.route("/api/environments", methods=["POST"])
def environments():
    data = request.get_json()
    # Process the data and generate the environments response
    response = {
        "message": "Environments data processed successfully",
        "data_received": data
    }
    return jsonify(response), 200

@app.route("/api/projects/<project_name>", methods=["POST"])
def projects_names(project_name):
    data = request.get_json()
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name
    }
    return jsonify(response), 200


@app.route("/api/projects/<project_name>/flows/<flow_id>", methods=["POST"])
def projects_flows(project_name, flow_id):
    data = request.get_json()
    # Process the data and generate the projects/flows response
    response = {
        "message": "Projects flows data processed successfully",
        "data_received": data,
        "project_name": project_name,
        "flow_id": flow_id
    }
    return jsonify(response), 200



@app.route("/api/projects/<project_name>/run-test", methods=["POST"])
def run_test(project_name):
    data = request.get_json()
    # Process the data and generate the run-test response
    response = {
        "project_name": project_name,
        "status": 1,
    }
    
    
    ## VANSHIKA PLZ SEND REQUEST TO API URL HERE.
    
    request_data = {
        
    }
    
    
    
    return jsonify(response), 200   



# API structure only. New handlers return 501 until their services are wired.
# TODO: Validate Supabase bearer tokens and project/environment/run ownership.
# TODO: Validate JSON, filters, pagination cursors, and Idempotency-Key headers.
# Existing POST handlers remain placeholders; service integration is not implemented.


## Projects and environments
@app.route("/api/projects", methods=["GET"])
def list_projects():
    # TODO: Fetch the authenticated user's accessible projects and return a paginated list.
    # Query: limit, cursor. Only projects accessible to the authenticated user.
    response = {"items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route("/api/environments", methods=["GET"])
def list_environments():
    # TODO: Check project access and fetch its environments with stable IDs and policies.
    # Required query: project_id. Optional: limit, cursor.
    response = {"items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route("/api/environments/<environment_id>", methods=["GET"])
def environment_details(environment_id):
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
    return jsonify(response), 501


@app.route("/api/projects/<project_id>/credential-references", methods=["GET"])
def list_credential_references(project_id):
    # TODO: Fetch this project's authorized credential IDs/names without exposing secrets.
    # Item: id, name, kind. Never include secret values or storage locators.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route("/api/projects/<project_id>/execution-policies", methods=["GET"])
def list_execution_policies(project_id):
    # TODO: Fetch this project's policy revisions, allowed modes and execution limits.
    # Item: id, name, revision, allowed_execution_modes, execution limits.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


## Existing flow configuration (separate from executed results)
@app.route("/api/projects/<project_id>/flows", methods=["GET"])
def list_flows(project_id):
    # TODO: Fetch project flows with environment-scoped last-run status/time and recent history.
    # Required query: environment_id. Optional: limit, cursor.
    # Item: id, project_id, name, current_revision_id, runnable, last_run.
    response = {"project_id": project_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route("/api/projects/<project_id>/flows/<flow_id>", methods=["GET"])
def flow_details(project_id, flow_id):
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
    return jsonify(response), 501


## Dashboard
@app.route("/api/dashboard", methods=["GET"])
def dashboard_summary():
    # TODO: Calculate full-period metrics/costs/regressions and fetch the latest five runs separately.
    # Required query: project_id, environment_id. Optional: timezone, as_of.
    # Aggregate the full reporting period independently of latest_runs.
    response = {
        "project_id": request.args.get("project_id"),
        "environment_id": request.args.get("environment_id"),
        "timezone": request.args.get("timezone", "UTC"),
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
    return jsonify(response), 501


# Shared route prefix; handlers still independently validate the ownership chain.
RUN_PATH = "/api/projects/<project_id>/environments/<environment_id>/runs"


@app.route(RUN_PATH, methods=["GET"])
def list_runs(project_id, environment_id):
    # TODO: Query persisted runs with filters, newest-first ordering and cursor pagination (default five).
    # Query: limit (default 5), cursor, flow_id, status, created_from, created_to.
    # Order: created_at DESC, id DESC. Preserve older runs; cursor pagination.
    response = {
        "project_id": project_id, "environment_id": environment_id,
        "items": [], "next_cursor": None,
    }
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>", methods=["GET"])
def run_details(project_id, environment_id, run_id):
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
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/reruns", methods=["POST"])
def rerun_test(project_id, environment_id, run_id):
    # TODO: Validate source/access, allocate a new run number and atomically save/enqueue an idempotent rerun.
    data = request.get_json()
    # Body: {} or {"configuration_source": "latest_flow"}.
    # Default: original configuration. Require terminal source + Idempotency-Key.
    # Once implemented: return 202 with a NEW persisted run ID and run_number.
    response = {
        "project_id": project_id, "environment_id": environment_id,
        "rerun_of_run_id": run_id, "data_received": data,
        "id": None, "run_number": None, "status": None,
    }
    return jsonify(response), 501


## Executed steps, actions, failures and evidence
@app.route(RUN_PATH + "/<run_id>/steps", methods=["GET"])
def run_steps(project_id, environment_id, run_id):
    # TODO: Fetch this run's executed steps and results in execution order with pagination.
    # Query: limit, cursor. Ordered by position, id.
    # Item: id, run_id, configured_step_id, position, name, status, timestamps.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/steps/<step_id>/actions", methods=["GET"])
def run_actions(project_id, environment_id, run_id, step_id):
    # TODO: Verify step ownership and fetch ordered actions with click metadata and screenshot links.
    # Query: limit, cursor. Ordered by run-wide action sequence.
    # Item includes status/times, click coordinates/viewport, before/after artifact IDs.
    response = {"run_id": run_id, "step_id": step_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/failures", methods=["GET"])
def run_failures(project_id, environment_id, run_id):
    # TODO: Load saved failure analysis, expected/observed results and linked evidence for this run.
    # Item: expected, observed, classification, likely_cause, suggested_next_steps,
    # analysis_status, evidence_artifact_ids and actual baseline run references.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/artifacts", methods=["GET"])
def run_artifacts(project_id, environment_id, run_id):
    # TODO: Fetch authorized artifact metadata and step/action links; apply filters and pagination.
    # Query: type, step_id, action_id, limit, cursor.
    # Screenshots, before/after images, console/network logs and trace metadata.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/artifacts/<artifact_id>/download", methods=["POST"])
def artifact_download(project_id, environment_id, run_id, artifact_id):
    # TODO: Verify artifact/run access and availability, then issue a five-minute signed download URL.
    # Authorize ownership, then issue a short-lived private object download URL.
    response = {"artifact_id": artifact_id, "url": None, "expires_at": None, "filename": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/logs", methods=["GET"])
def run_logs(project_id, environment_id, run_id):
    # TODO: Fetch filtered, paginated console/network logs with redaction and response size limits.
    # Query: kind (console/network), artifact_id, level, from, to, limit, cursor.
    # Paginate redacted entries; do not embed large logs in run detail.
    response = {"run_id": run_id, "items": [], "next_cursor": None, "truncated": False}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/ai-usage", methods=["GET"])
def run_ai_usage(project_id, environment_id, run_id):
    # TODO: Fetch usage records and calculate the full run total with pending/partial/final cost state.
    # Query: limit, cursor. Total covers all run usage, not just this page.
    response = {
        "run_id": run_id, "items": [], "next_cursor": None,
        "total": {"amount": None, "currency": "USD", "status": "pending"},
    }
    return jsonify(response), 501


@app.route("/api/projects/<project_id>/environments/<environment_id>/regressions", methods=["GET"])
def list_regressions(project_id, environment_id):
    # TODO: Fetch real environment regression records with baseline references and pagination.
    # Query: state (default active), limit, cursor. Return real failure metadata.
    response = {"items": [], "next_cursor": None}
    return jsonify(response), 501


## Run discussion
@app.route(RUN_PATH + "/<run_id>/comments", methods=["GET"])
def list_run_comments(project_id, environment_id, run_id):
    # TODO: Fetch persisted run comments with author display names and timestamps in order.
    # Query: limit, cursor. Item: id, text, author {id, display_name}, created_at.
    response = {"run_id": run_id, "items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route(RUN_PATH + "/<run_id>/comments", methods=["POST"])
def create_run_comment(project_id, environment_id, run_id):
    # TODO: Validate text/access and idempotently save a comment using the authenticated author.
    data = request.get_json()
    # Body: {"text": "..."}. Derive author from session; require Idempotency-Key.
    # Once persisted: return 201 with comment ID, author and timestamp.
    response = {"run_id": run_id, "data_received": data, "id": None, "author": None, "created_at": None}
    return jsonify(response), 501


## Notifications
@app.route("/api/notifications", methods=["GET"])
def list_notifications():
    # TODO: Fetch this user's accessible notifications with read filters and pagination.
    # Query: read, project_id, environment_id, limit, cursor. Session recipient only.
    # Item: id, recipient_id, run_id/number, project/environment, type, title,
    # message, created_at, read_at. Completion retries must not duplicate rows.
    response = {"items": [], "next_cursor": None}
    return jsonify(response), 501


@app.route("/api/notifications/unread-count", methods=["GET"])
def notification_unread_count():
    # TODO: Count all accessible unread notifications for the authenticated user and filters.
    # Optional query: project_id, environment_id. Count all accessible unread rows.
    response = {"unread_count": None}
    return jsonify(response), 501


@app.route("/api/notifications/<notification_id>", methods=["PATCH"])
def mark_notification_read(notification_id):
    # TODO: Verify recipient/access and persist the first read timestamp without changing it on retries.
    data = request.get_json()
    # Body: {"read": true}. Session recipient only; preserve first read timestamp.
    response = {"id": notification_id, "data_received": data, "read_at": None}
    return jsonify(response), 501


## Live updates (transport not implemented)
@app.route(RUN_PATH + "/<run_id>/events", methods=["GET"])
def run_events(project_id, environment_id, run_id):
    # TODO: text/event-stream with durable per-run IDs and Last-Event-ID/after.
    # Events: run/step/action, screenshot, analysis, completion, usage/artifacts.
    # Persist before publish; replay ordered events; FE deduplicates and refetches.
    response = {"message": "Run event streaming is not implemented", "run_id": run_id}
    return jsonify(response), 501


@app.route("/api/events", methods=["GET"])
def user_events():
    # TODO: Authenticated user SSE for notification.created/read, run.updated,
    # dashboard.invalidated. Support reconnect/resume and membership changes.
    response = {"message": "User event streaming is not implemented"}
    return jsonify(response), 501


## Internal service callbacks (separate service authentication required)
@app.route("/internal/v1/runs/<run_id>/execution-events", methods=["POST"])
def receive_execution_event(run_id):
    # TODO: Authenticate the worker/job, deduplicate/order events, save results and publish durable updates.
    # Body: event_id, job_id, attempt, sequence, type, occurred_at,
    # schema_version, payload. Deduplicate and validate job/run binding.
    # Do not accept events or echo potentially sensitive executor payloads yet.
    response = {"message": "Execution event ingestion is not implemented", "run_id": run_id}
    return jsonify(response), 501


@app.route("/internal/v1/runs/<run_id>/ai-usage", methods=["POST"])
def receive_ai_usage(run_id):
    # TODO: Authenticate the service and persist usage revisions idempotently; update costs and notify FE.
    # Body: usage_id, event_id, revision, cost_session_id, job_id, attempt,
    # provider, model, operation, tokens, amount, currency, status, timestamps.
    # AI service must durably save usage before delivery. Idempotent BE upsert.
    response = {"message": "AI usage ingestion is not implemented", "run_id": run_id}
    return jsonify(response), 501


@app.route("/internal/v1/runs/<run_id>/ai-cost-finalizations", methods=["POST"])
def finalize_ai_cost(run_id):
    # TODO: Authenticate the service and verify all expected final usage before saving final cost state.
    # Body: event_id, cost_session_id, revision, final_usage_count/digest, closed_at.
    # Finalize only after all final usage matches; completion alone is insufficient.
    response = {"message": "AI cost finalization is not implemented", "run_id": run_id}
    return jsonify(response), 501


# Register every route before starting the development server.
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
