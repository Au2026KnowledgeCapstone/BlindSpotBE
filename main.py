"""BlindSpot backend : the complete API surface.

Public product routes are declared in this file and app/services/.
"""
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from app.core.auth import (
    csrf_guard,
    current_auth_user,
    email_destination,
    recovery_user,
    register_auth,
    set_session,
)
from app.core import auth_pkce as pkce
from app.core.deps import CurrentUser, Db, Paged, ProjectAccess, ProjectManage
from app.core.errors import ServiceError, register_exception_handlers, validation_error_handler
from app.core.observability import RequestIdMiddleware, configure_logging
from app.core.supabase_auth import supabase_request
from app.schemas.auth import (
    AuthResult,
    Credentials,
    EmptyRequest,
    Message,
    PasswordUpdate,
    ResetRequest,
    SignupCredentials,
    User,
)
from app.schemas.common import Acknowledged, ErrorResponse, Page
from app.schemas.environments import Environment, EnvironmentCreate, EnvironmentUpdate
from app.schemas.identity import (
    Invitation,
    InvitationCreate,
    Me,
    Member,
    Notification,
    NotificationUpdate,
    Project,
    ProjectCreate,
    ProjectUpdate,
    UnreadCount,
)
from app.schemas.internal import AIUsageReport, CostFinalization, ExecutionEvent
from app.schemas.requirements import (
    ApprovalRequest,
    ImportResult,
    Requirement,
    RequirementCreate,
    RequirementUpdate,
)
from app.schemas.runs import Result, Run, RunCreate, RunUsage
from app.services import resources, analysis, callbacks, events, imports, private_storage, verification
from app.services.workspace_routes import router as workspace_router
from app.services.auth import (
    complete_pkce_callback,
    logout_session,
    refresh_session,
    request_password_reset,
    signup_session,
    update_password,
)

configure_logging("api")

DESCRIPTION = """
Requirements-driven product validation. A product manager imports requirements
from their own documents, approves what the product is supposed to do, and
BlindSpot runs those requirements against the real application in a browser.

Every verdict comes back with the evidence behind it, and anything a model
inferred stays visibly separate from what was actually observed.
"""

TAGS = [
    {"name": "Health", "description": "Liveness. No authentication."},
    {"name": "Auth", "description": "Backend-owned Supabase sessions: signup, login, logout, password reset."},
    {"name": "Identity", "description": "The signed-in user, and their notifications."},
    {"name": "Projects", "description": "Projects, membership and invitations."},
    {"name": "Requirements", "description": "What the product should do, and who approved it."},
    {"name": "Imports", "description": "Extracting requirements from uploaded documents."},
    {"name": "Environments", "description": "Where an application lives, and how to log in."},
    {"name": "Analysis", "description": "Runs, their per-requirement results, and cost."},
    {"name": "Evidence", "description": "Screenshots and captured page content."},
    {"name": "Internal", "description": "Called by aiservice only. Never by the frontend."},
]

app = FastAPI(
    title="BlindSpot Backend",
    version="0.1.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required."},
        404: {"model": ErrorResponse, "description": "Not found, or not yours."},
        503: {"model": ErrorResponse, "description": "A required service is unavailable."},
    },
)
app.add_middleware(RequestIdMiddleware)
register_exception_handlers(app)
register_auth(app)
app.include_router(workspace_router)


@app.exception_handler(RequestValidationError)
async def validation_error_redacting_auth_input(request: Request, exc: RequestValidationError):
    # FastAPI's default validation response echoes the rejected input, which
    # on an /auth/* body could be a password. Fixed message there; the
    # envelope-shaped handler from register_exception_handlers everywhere else.
    if request.url.path.startswith("/auth/"):
        return JSONResponse(
            status_code=422, content={"error": {"code": "validation_error", "message": "Invalid authentication request."}}
        )
    return await validation_error_handler(request, exc)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/", tags=["Health"], summary="Liveness check")
def liveness(db: Db) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth — backend-owned. The frontend never holds a token; BE issues httpOnly
# session cookies and verifies every one of them against Supabase. Ported
# from feat/backend-auth; logic unchanged, relocated onto this file's
# every-route-lives-here convention and app/core/app/services layout.
# ---------------------------------------------------------------------------


@app.post("/auth/signup", response_model=AuthResult, tags=["Auth"], dependencies=[Depends(csrf_guard)])
async def signup(credentials: SignupCredentials, request: Request, response: Response) -> AuthResult:
    return await signup_session(request, response, credentials)


@app.post("/auth/login", response_model=AuthResult, tags=["Auth"], dependencies=[Depends(csrf_guard)])
async def login(credentials: Credentials, request: Request, response: Response) -> AuthResult:
    data = await supabase_request(
        request, "POST", "/token", params={"grant_type": "password"},
        body={"email": str(credentials.email), "password": credentials.password.get_secret_value()},
    )
    user = set_session(response, data, request.app.state.auth_settings)
    return AuthResult(user=user, authenticated=True)


@app.get("/auth/me", response_model=User, tags=["Auth"])
async def auth_me(user: User = Depends(current_auth_user)) -> User:
    return user


@app.post("/auth/refresh", response_model=AuthResult, tags=["Auth"], dependencies=[Depends(csrf_guard)])
async def refresh(payload: EmptyRequest, request: Request, response: Response) -> AuthResult:
    return await refresh_session(request, response)


@app.post("/auth/logout", response_model=Message, tags=["Auth"], dependencies=[Depends(csrf_guard)])
async def logout(payload: EmptyRequest, request: Request, response: Response) -> Message:
    return Message(message=await logout_session(request, response))


@app.get(
    "/auth/callback/{purpose}/{transaction_id}",
    status_code=303,
    response_class=RedirectResponse,
    tags=["Auth"],
)
async def pkce_callback(purpose: Literal["signup", "recovery"], transaction_id: str, request: Request):
    destination = email_destination(request, "email" if purpose == "signup" else "recovery")
    response = RedirectResponse(destination, status_code=303)
    await complete_pkce_callback(request, response, purpose, transaction_id)
    return response


@app.get("/auth/recovery", response_model=User, tags=["Auth"])
async def recovery_status(user: User = Depends(recovery_user)) -> User:
    return user


@app.post(
    "/auth/password/reset-request", response_model=Message, tags=["Auth"], dependencies=[Depends(csrf_guard)]
)
async def password_reset_request(payload: ResetRequest, request: Request, response: Response) -> Message:
    return await request_password_reset(request, response, payload)


@app.post("/auth/password/update", response_model=Message, tags=["Auth"], dependencies=[Depends(csrf_guard)])
async def password_update(
    payload: PasswordUpdate, request: Request, response: Response, user: User = Depends(recovery_user)
) -> Message:
    return Message(message=await update_password(request, response, payload))


# Identity and project routes are implemented in app/services/workspace_routes.py.


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


@app.get(
    "/projects/{pid}/requirements",
    tags=["Requirements"],
    summary="List a project's requirements",
    response_model=Page[Requirement],
    description="Search covers title, description, criteria text and id. Filters compose.",
)
def list_requirements(
    db: Db, context: ProjectAccess,
    page: Paged,
    q: Annotated[str | None, Query(description="Free-text search.")] = None,
    category: Annotated[str | None, Query()] = None,
    priority: Annotated[str | None, Query()] = None,
    approval_status: Annotated[str | None, Query()] = None,
) -> Page[Requirement]:
    return resources.list_requirements(db, context, page, q, category=category, priority=priority, approval_status=approval_status)


@app.post(
    "/projects/{pid}/requirements",
    tags=["Requirements"],
    summary="Create a requirement",
    status_code=201,
    response_model=Requirement,
)
def create_requirement(db: Db, context: ProjectAccess, body: RequirementCreate) -> Requirement:
    return resources.create_requirement(db, context, body)


@app.get(
    "/projects/{pid}/requirements/{rid}",
    tags=["Requirements"],
    summary="Get a requirement",
    response_model=Requirement,
)
def get_requirement(db: Db, context: ProjectAccess, rid: str) -> Requirement:
    return resources.requirement_out(db, resources.scoped(db, resources.Requirement, context.project_id, rid))


@app.patch(
    "/projects/{pid}/requirements/{rid}",
    tags=["Requirements"],
    summary="Update a requirement",
    response_model=Requirement,
    description=(
        "Sending acceptance_criteria replaces the whole set; the server reconciles by id in one "
        "transaction. Editing title, description or criteria resets approval to draft."
    ),
)
def update_requirement(db: Db, context: ProjectAccess, rid: str, body: RequirementUpdate) -> Requirement:
    return resources.update_requirement(db, context, rid, body)


@app.delete(
    "/projects/{pid}/requirements/{rid}",
    tags=["Requirements"],
    summary="Delete a requirement",
    status_code=204,
)
def delete_requirement(db: Db, context: ProjectAccess, rid: str) -> None:
    return resources.delete_requirement(db, context, rid)


@app.post(
    "/projects/{pid}/requirements/{rid}/approval",
    tags=["Requirements"],
    summary="Approve a requirement",
    response_model=Requirement,
    description=(
        "Approval records that a requirement is correctly captured. It is not a test result. "
        "A requirement needing clarification cannot be approved until it has been edited."
    ),
)
def approve_requirement(db: Db, context: ProjectAccess, rid: str, body: ApprovalRequest) -> Requirement:
    return resources.approve_requirement(db, context, rid, body)


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


@app.post(
    "/projects/{pid}/imports",
    tags=["Imports"],
    summary="Import requirements from documents",
    status_code=201,
    response_model=ImportResult,
    description=(
        "Forwards the documents to aiservice, which extracts requirements and cites the exact "
        "source passages. Everything lands as a draft; nothing is auto-approved. "
        "BE never calls a model itself."
    ),
)
async def create_import(
    context: ProjectAccess, db: Db, request: Request,
    brd: Annotated[UploadFile, File(description="Business requirements document.")],
    srs: Annotated[UploadFile, File(description="Software requirements specification.")],
    design_spec: Annotated[UploadFile | None, File(description="Optional design specification.")] = None,
) -> ImportResult:
    return await imports.create_import(db, context, request, brd, srs, design_spec)


@app.get(
    "/projects/{pid}/imports/{iid}",
    tags=["Imports"],
    summary="Get an import and what it produced",
    response_model=ImportResult,
)
def get_import(db: Db, context: ProjectAccess, iid: str) -> ImportResult:
    return imports.get_import(db, context, iid)


@app.get(
    "/projects/{pid}/imports/{iid}/documents/{did}",
    tags=["Imports"],
    summary="Download a source document",
    status_code=302,
    description="Redirects to a short-lived signed URL. Source documents are retained so a reviewer can open the original.",
)
def download_document(db: Db, context: ProjectAccess, iid: str, did: str, request: Request):
    return private_storage.download_document(db, context, iid, did, request)


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


@app.get(
    "/projects/{pid}/environments",
    tags=["Environments"],
    summary="List a project's environments",
    response_model=Page[Environment],
)
def list_environments(db: Db, context: ProjectAccess, page: Paged) -> Page[Environment]:
    return resources.paginate(db, resources.select(resources.Environment).where(resources.Environment.project_id == resources.uid(context.project_id)), resources.Environment, page, resources.environment_out)


@app.get(
    "/projects/{pid}/environments/{eid}",
    tags=["Environments"],
    summary="Get an environment",
    response_model=Environment,
)
def get_environment(db: Db, context: ProjectAccess, eid: str) -> Environment:
    return resources.environment_out(resources.scoped(db, resources.Environment, context.project_id, eid))


@app.patch(
    "/projects/{pid}/environments/{eid}",
    tags=["Environments"],
    summary="Update an environment",
    response_model=Environment,
    description="Changing base_url clears verification and bumps revision, invalidating any saved plan.",
)
def update_environment(db: Db, context: ProjectManage, eid: str, body: EnvironmentUpdate) -> Environment:
    return resources.update_environment(db, context, eid, body)


@app.post(
    "/projects/{pid}/environments/{eid}/verify",
    tags=["Environments"],
    summary="Check that the saved login works",
    status_code=202,
    response_model=Acknowledged,
)
async def verify_environment(db: Db, context: ProjectManage, eid: str, request: Request) -> Acknowledged:
    return await verification.verify(db, context, eid, request)


# ---------------------------------------------------------------------------
# Analysis runs
# ---------------------------------------------------------------------------


@app.get(
    "/projects/{pid}/environments/{eid}/runs",
    tags=["Analysis"],
    summary="List runs for an environment",
    response_model=Page[Run],
)
def list_runs(
    db: Db, context: ProjectAccess,
    eid: str,
    page: Paged,
    status: Annotated[str | None, Query(description="Filter by run status.")] = None,
) -> Page[Run]:
    return analysis.list_runs(db, context, eid, page, status)


@app.post(
    "/projects/{pid}/environments/{eid}/runs",
    tags=["Analysis"],
    summary="Queue a run",
    status_code=202,
    response_model=Run,
    description=(
        "Only approved requirements may be selected, at most ten per run. The run and its "
        "dispatch intent are saved in one transaction before aiservice is contacted, so a "
        "failed dispatch is retried from what was saved rather than lost. Send Idempotency-Key to safely retry submissions."
    ),
)
def create_run(db: Db, context: ProjectAccess, eid: str, body: RunCreate, request: Request) -> Run:
    return analysis.create_run(db, context, eid, body, request.headers.get("idempotency-key"))


@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}",
    tags=["Analysis"],
    summary="Get a run",
    response_model=Run,
)
def get_run(db: Db, context: ProjectAccess, eid: str, runid: str) -> Run:
    return analysis.run_out(db, analysis.get_run(db, context, eid, runid))


@app.post(
    "/projects/{pid}/environments/{eid}/runs/{runid}/cancel",
    tags=["Analysis"],
    summary="Cancel a run",
    status_code=202,
    response_model=Acknowledged,
)
def cancel_run(db: Db, context: ProjectAccess, eid: str, runid: str) -> Acknowledged:
    return analysis.cancel_run(db, context, eid, runid)


@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/results",
    tags=["Analysis"],
    summary="List a run's per-requirement results",
    response_model=Page[Result],
)
def list_results(db: Db, context: ProjectAccess, eid: str, runid: str, page: Paged) -> Page[Result]:
    return analysis.list_results(db, context, eid, runid, page)


@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/results/{resid}",
    tags=["Analysis"],
    summary="Get one result, with its evidence",
    response_model=Result,
)
def get_result(db: Db, context: ProjectAccess, eid: str, runid: str, resid: str) -> Result:
    return analysis.get_result(db, context, eid, runid, resid)


@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/events",
    tags=["Analysis"],
    summary="Stream live run events",
    description=(
        "Server-sent events. Reconnect with Last-Event-ID to replay what was missed; "
        "refetch the run on completion rather than trusting the stream alone."
    ),
)
def stream_run_events(db: Db, context: ProjectAccess, eid: str, runid: str, request: Request):
    return events.stream(db, context, eid, runid, request)


@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/ai-usage",
    tags=["Analysis"],
    summary="What a run cost",
    response_model=RunUsage,
    description="Pending is not zero. Cost may arrive after a run finishes and is final only once everything expected has.",
)
def run_usage(db: Db, context: ProjectAccess, eid: str, runid: str) -> RunUsage:
    return analysis.usage_out(db, analysis.get_run(db, context, eid, runid))


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@app.get(
    "/evidence/{eid}",
    tags=["Evidence"],
    summary="Fetch an evidence artifact",
    status_code=302,
    description="Redirects to a short-lived signed URL. Evidence is served by id, never by storage path.",
)
async def get_evidence(db: Db, user: CurrentUser, eid: str, request: Request):
    return await private_storage.get_evidence(db, user, eid, request)


# ---------------------------------------------------------------------------
# Internal — aiservice only
#
# Three rules hold whatever the field shapes become: persist before publishing,
# deduplicate on the event id, and mark cost final only when the expected usage
# has actually arrived. Authenticated with the job-scoped credential BE issued
# at dispatch, not a shared key.
# ---------------------------------------------------------------------------


@app.post(
    "/internal/v1/runs/{runid}/execution-events",
    tags=["Internal"],
    summary="Receive execution events from aiservice",
    status_code=202,
    response_model=Acknowledged,
    description="Deduplicated on event_id and ordered by sequence. Persisted before being published to the live stream.",
)
def receive_execution_event(db: Db, request: Request, runid: str, body: ExecutionEvent) -> Acknowledged:
    return callbacks.execution(db, runid, request.headers.get("authorization"), body)


@app.post(
    "/internal/v1/runs/{runid}/ai-usage",
    tags=["Internal"],
    summary="Receive AI usage from aiservice",
    status_code=202,
    response_model=Acknowledged,
    description="Idempotent on usage_id. A revision replaces an estimate rather than adding a second charge.",
)
def receive_ai_usage(db: Db, request: Request, runid: str, body: AIUsageReport) -> Acknowledged:
    return callbacks.usage(db, runid, request.headers.get("authorization"), body)


@app.post(
    "/internal/v1/runs/{runid}/ai-cost-finalizations",
    tags=["Internal"],
    summary="Close out a run's cost",
    status_code=202,
    response_model=Acknowledged,
    description="Cost becomes final only when the reported usage count matches. Run completion alone is not sufficient.",
)
def finalize_ai_cost(db: Db, request: Request, runid: str, body: CostFinalization) -> Acknowledged:
    return callbacks.finalize(db, runid, request.headers.get("authorization"), body)


@app.get("/downloads/{token}", tags=["Evidence"], summary="Redeem a private five-minute download grant")
def download_private_object(db: Db, user: CurrentUser, token: str):
    return private_storage.download(db, user, token)
