"""BlindSpot backend : the complete API surface.

Public product routes are declared in this file and app/services/.
"""
from typing import Annotated, Literal
import uuid
from uuid import UUID
import json
import time
from sqlalchemy.orm import Session
from app.core.db import get_db
from fastapi import Header
from fastapi.responses import StreamingResponse

from app.models import RunExecutionEvent
from sqlalchemy import select
from app.models import CriterionAssessment, Evidence
from app.schemas.runs import (
    CriterionAssessment,
    Action,
    Evidence,
)
from app.models import (
    CriterionAssessment as CriterionAssessmentModel,
    Evidence as EvidenceModel,
)
from app.schemas.runs import (
    CriterionAssessment as CriterionAssessmentSchema,
    Action as ActionSchema,
    Evidence as EvidenceSchema,
)
from app.models import (
    Action,
    AnalysisRun,
    CriterionAssessment,
    Environment as EnvironmentModel,
    Evidence as EvidenceModel,
    Result as ResultModel,
)
from app.models.requirements import AcceptanceCriterion, Requirement
from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy import func, select, text, tuple_
from app.models import Action, AIUsage, AnalysisRun, Environment, Result
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
        501: {"model": ErrorResponse, "description": "Declared, not yet implemented."},
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


def todo(handoff: str, what: str) -> ServiceError:
    """A declared endpoint with no implementation yet.

    Never a fake success. The message names what it is waiting on, so
    'unfinished' is distinguishable from 'broken' at a glance.
    """
    return ServiceError("not_implemented", f"Not yet implemented. {what} lands in {handoff}.", 501)


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


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/requirements",
    tags=["Requirements"],
    summary="List a project's requirements",
    response_model=Page[Requirement],
    description="Search covers title, description, criteria text and id. Filters compose.",
)
def list_requirements(
    context: ProjectAccess,
    page: Paged,
    q: Annotated[str | None, Query(description="Free-text search.")] = None,
    category: Annotated[str | None, Query()] = None,
    priority: Annotated[str | None, Query()] = None,
    approval_status: Annotated[str | None, Query()] = None,
) -> Page[Requirement]:
    raise todo("B4", "Requirements")


# SRINIVAS, WORK ON THESE
@app.post(
    "/projects/{pid}/requirements",
    tags=["Requirements"],
    summary="Create a requirement",
    status_code=201,
    response_model=Requirement,
)
def create_requirement(context: ProjectAccess, body: RequirementCreate) -> Requirement:
    raise todo("B4", "Requirements")


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/requirements/{rid}",
    tags=["Requirements"],
    summary="Get a requirement",
    response_model=Requirement,
)
def get_requirement(context: ProjectAccess, rid: str) -> Requirement:
    raise todo("B4", "Requirements")


# SRINIVAS, WORK ON THESE
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
def update_requirement(context: ProjectAccess, rid: str, body: RequirementUpdate) -> Requirement:
    raise todo("B4", "Requirements")


# SRINIVAS, WORK ON THESE
@app.delete(
    "/projects/{pid}/requirements/{rid}",
    tags=["Requirements"],
    summary="Delete a requirement",
    status_code=204,
)
def delete_requirement(context: ProjectAccess, rid: str) -> None:
    raise todo("B4", "Requirements")


# SRINIVAS, WORK ON THESE
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
def approve_requirement(context: ProjectAccess, rid: str, body: ApprovalRequest) -> Requirement:
    raise todo("B4", "Approval")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


# SRINIVAS, WORK ON THESE
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
    context: ProjectAccess,
    brd: Annotated[UploadFile, File(description="Business requirements document.")],
    srs: Annotated[UploadFile, File(description="Software requirements specification.")],
    design_spec: Annotated[UploadFile | None, File(description="Optional design specification.")] = None,
) -> ImportResult:
    raise todo("B7", "Document import")


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/imports/{iid}",
    tags=["Imports"],
    summary="Get an import and what it produced",
    response_model=ImportResult,
)
def get_import(context: ProjectAccess, iid: str) -> ImportResult:
    raise todo("B7", "Document import")


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/imports/{iid}/documents/{did}",
    tags=["Imports"],
    summary="Download a source document",
    status_code=302,
    description="Redirects to a short-lived signed URL. Source documents are retained so a reviewer can open the original.",
)
def download_document(context: ProjectAccess, iid: str, did: str) -> None:
    raise todo("B7", "Document storage")


# ---------------------------------------------------------------------------
# Environments, @SRINIVAS WE MAY HAVE TO RENAME ENVIRONMENTS TO BROWSE CONFIG
# ---------------------------------------------------------------------------


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/environments",
    tags=["Environments"],
    summary="List a project's environments",
    response_model=Page[Environment],
)
def list_environments(context: ProjectAccess, page: Paged) -> Page[Environment]:
    raise todo("B5", "Environments")


# SRINIVAS, WORK ON THESE
@app.get(
    "/projects/{pid}/environments/{eid}",
    tags=["Environments"],
    summary="Get an environment",
    response_model=Environment,
)
def get_environment(context: ProjectAccess, eid: str) -> Environment:
    raise todo("B5", "Environments")


# SRINIVAS, WORK ON THESE
@app.patch(
    "/projects/{pid}/environments/{eid}",
    tags=["Environments"],
    summary="Update an environment",
    response_model=Environment,
    description="Changing base_url clears verification and bumps revision, invalidating any saved plan.",
)
def update_environment(context: ProjectManage, eid: str, body: EnvironmentUpdate) -> Environment:
    raise todo("B5", "Environments")


# SRINIVAS, WORK ON THESE
@app.post(
    "/projects/{pid}/environments/{eid}/verify",
    tags=["Environments"],
    summary="Check that the saved login works",
    status_code=202,
    response_model=Acknowledged,
)
def verify_environment(context: ProjectManage, eid: str) -> Acknowledged:
    raise todo("B6", "Login verification")


# ---------------------------------------------------------------------------
# Analysis runs
# ---------------------------------------------------------------------------


# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs",
    tags=["Analysis"],
    summary="List runs for an environment",
    response_model=Page[Run],
)
def list_runs(
    context: ProjectAccess,
    eid: str,
    page: Paged,
    db: Db,
    status: Annotated[str | None, Query(description="Filter by run status.")] = None,
) -> Page[Run]:
    # Validate the optional status filter.
    valid_statuses = {"queued", "running", "completed", "failed", "cancelled"}

    if status is not None and status not in valid_statuses:
        raise ServiceError(
            "invalid_status",
            "Invalid run status.",
            status_code=422,
        )

    # Validate the environment belongs to the authorized project.
    try:
        environment_id = uuid.UUID(eid)
    except ValueError:
        raise ServiceError(
            "not_found",
            "Environment not found.",
            status_code=404,
        )

    environment = db.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == uuid.UUID(context.project_id),
        )
    )

    if environment is None:
        raise ServiceError(
            "not_found",
            "Environment not found.",
            status_code=404,
        )

    # Count actions belonging to each run through its results.
    action_count = (
        select(func.count(Action.id))
        .select_from(Action)
        .join(Result, Action.result_id == Result.id)
        .where(
            Result.project_id == AnalysisRun.project_id,
            Result.analysis_run_id == AnalysisRun.id,
        )
        .correlate(AnalysisRun)
        .scalar_subquery()
    )

    # Sum recorded USD usage for each run.
    estimated_cost = (
        select(func.sum(AIUsage.amount))
        .where(
            AIUsage.project_id == AnalysisRun.project_id,
            AIUsage.analysis_run_id == AnalysisRun.id,
            AIUsage.currency == "USD",
        )
        .correlate(AnalysisRun)
        .scalar_subquery()
    )

    # Build the project/environment-scoped query.
    query = select(
        AnalysisRun,
        action_count.label("action_count"),
        estimated_cost.label("estimated_cost_usd"),
    ).where(
        AnalysisRun.project_id == uuid.UUID(context.project_id),
        AnalysisRun.environment_id == environment_id,
    )

    if status is not None:
        query = query.where(AnalysisRun.status == status)

    # Resolve cursor against the same environment and project.
    if page.cursor:
        try:
            cursor_id = uuid.UUID(page.cursor)
        except ValueError:
            raise ServiceError(
                "invalid_cursor",
                "Invalid pagination cursor.",
                status_code=422,
            )

        cursor_run = db.scalar(
            select(AnalysisRun).where(
                AnalysisRun.id == cursor_id,
                AnalysisRun.project_id == uuid.UUID(context.project_id),
                AnalysisRun.environment_id == environment_id,
            )
        )

        if cursor_run is None:
            raise ServiceError(
                "invalid_cursor",
                "Pagination cursor not found.",
                status_code=422,
            )

        query = query.where(
            tuple_(AnalysisRun.queued_at, AnalysisRun.id)
            < tuple_(cursor_run.queued_at, cursor_run.id)
        )

    # Newest first, with ID as a deterministic tie-breaker.
    query = query.order_by(
        AnalysisRun.queued_at.desc(),
        AnalysisRun.id.desc(),
    )

    # Fetch one extra row to determine whether another page exists.
    rows = db.execute(query.limit(page.limit + 1)).all()

    has_more = len(rows) > page.limit
    rows = rows[:page.limit]

    items = [
        Run(
            id=str(run.id),
            run_number=run.run_number,
            project_id=str(run.project_id),
            environment_id=str(run.environment_id),
            status=run.status,
            engine=run.engine,
            requirement_snapshots=run.requirement_snapshots,
            requested_by=str(run.requested_by),
            queued_at=run.queued_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            action_count=count,
            estimated_cost_usd=float(cost) if cost is not None else None,
            error=run.error,
        )
        for run, count, cost in rows
    ]

    return Page[Run](
        items=items,
        next_cursor=str(rows[-1][0].id) if has_more and rows else None,
    )


# Nishitha, WORK ON THIS
@app.post(
    "/projects/{pid}/environments/{eid}/runs",
    tags=["Analysis"],
    summary="Queue a run",
    status_code=202,
    response_model=Run,
    description=(
        "Only approved requirements may be selected, at most ten per run. The run and its "
        "dispatch intent are saved in one transaction before aiservice is contacted, so a "
        "failed dispatch is retried from what was saved rather than lost."
    ),
)
def create_run(context: ProjectAccess, eid: str, body: RunCreate, db: Db) -> Run:
    try:
        environment_id = UUID(eid)
    except ValueError:
        raise ServiceError("not_found", "Environment not found.", 404)

    project_id = UUID(context.project_id)

    # Verify that the environment belongs to this project.
    environment = db.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
        )
    )

    if environment is None:
        raise ServiceError("not_found", "Environment not found.", 404)

    # Reject duplicate requirement IDs.
    if len(body.requirement_ids) != len(set(body.requirement_ids)):
        raise ServiceError(
            "invalid_requirements",
            "Duplicate requirement IDs are not allowed.",
            422,
        )

    try:
        requirement_ids = [UUID(rid) for rid in body.requirement_ids]
    except ValueError:
        raise ServiceError(
            "invalid_requirements",
            "Invalid requirement ID.",
            422,
        )

    # Retrieve requirements belonging to this project.
    requirements = db.scalars(
        select(Requirement).where(
            Requirement.project_id == project_id,
            Requirement.id.in_(requirement_ids),
        )
    ).all()

    if len(requirements) != len(requirement_ids):
        raise ServiceError(
            "invalid_requirements",
            "One or more requirements were not found.",
            404,
        )

    # Only approved requirements can be executed.
    if any(r.approval_status != "approved" for r in requirements):
        raise ServiceError(
            "invalid_requirements",
            "All selected requirements must be approved.",
            422,
        )

    # Lock project row while allocating the next run number.
    from app.models.public import Project

    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
    )

    if project is None:
        raise ServiceError("not_found", "Project not found.", 404)

    last_run_number = db.scalar(
        select(func.max(AnalysisRun.run_number)).where(
            AnalysisRun.project_id == project_id
        )
    ) or 0

    run = AnalysisRun(
        project_id=project_id,
        environment_id=environment_id,
        run_number=last_run_number + 1,
        engine="mvp",
        status="queued",
        requested_by=UUID(context.user.user_id),
        requirement_snapshots=[
            {"id": str(r.id), "title": r.title}
            for r in requirements
        ],
    )

    try:
        db.add(run)
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise

    return Run(
        id=str(run.id),
        run_number=run.run_number,
        project_id=str(run.project_id),
        environment_id=str(run.environment_id),
        status=run.status,
        engine=run.engine,
        requirement_snapshots=run.requirement_snapshots,
        requested_by=str(run.requested_by),
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        action_count=0,
        estimated_cost_usd=None,
        error=run.error,
    )


# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}",
    tags=["Analysis"],
    summary="Get a run",
    response_model=Run,
)
def get_run(context: ProjectAccess, eid: str, runid: str, db: Db) -> Run:
    try:
        environment_id = UUID(eid)
        run_id = UUID(runid)
    except ValueError:
        raise ServiceError("not_found", "Run not found.", 404)

    project_id = UUID(context.project_id)

    # Verify environment belongs to the authorized project.
    environment = db.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
        )
    )

    if environment is None:
        raise ServiceError("not_found", "Run not found.", 404)

    # Find the run within the same project and environment.
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
    )

    if run is None:
        raise ServiceError("not_found", "Run not found.", 404)

    return Run(
        id=str(run.id),
        run_number=run.run_number,
        project_id=str(run.project_id),
        environment_id=str(run.environment_id),
        status=run.status,
        engine=run.engine,
        requirement_snapshots=run.requirement_snapshots,
        requested_by=str(run.requested_by),
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        action_count=0,
        estimated_cost_usd=None,
        error=run.error,
    )


# Nishitha, WORK ON THIS
@app.post(
    "/projects/{pid}/environments/{eid}/runs/{runid}/cancel",
    tags=["Analysis"],
    summary="Cancel a run",
    status_code=202,
    response_model=Acknowledged,
)
def cancel_run(context: ProjectAccess, eid: str, runid: str, db: Db) -> Acknowledged:
    try:
        environment_id = UUID(eid)
        run_id = UUID(runid)
    except ValueError:
        raise ServiceError("not_found", "Run not found.", 404)

    project_id = UUID(context.project_id)

    # Verify environment ownership.
    environment = db.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.project_id == project_id,
        )
    )

    if environment is None:
        raise ServiceError("not_found", "Run not found.", 404)

    # Lock the run to prevent conflicting state changes.
    run = db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
        .with_for_update()
    )

    if run is None:
        raise ServiceError("not_found", "Run not found.", 404)

    if run.status in ("completed", "failed", "cancelled"):
        raise ServiceError(
            "invalid_run_state",
            f"Cannot cancel a run with status '{run.status}'.",
            409,
        )

    try:
        if run.status == "queued":
            run.status = "cancelled"
        else:
            # Running jobs should receive a cancellation request.
            run.cancel_requested = True

        db.commit()

    except Exception:
        db.rollback()
        raise

    return Acknowledged(status="cancelled" if run.status == "cancelled" else "cancellation_requested")


# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/results",
    tags=["Analysis"],
    summary="List a run's per-requirement results",
    response_model=Page[Result],
)
def list_results(context: ProjectAccess, eid: str, runid: str, page: Paged, db: Db) -> Page[Result]:
    # Validate IDs.
    try:
        project_id = uuid.UUID(context.project_id)
        environment_id = uuid.UUID(eid)
        run_id = uuid.UUID(runid)
    except ValueError:
        raise ServiceError("not_found", "Run not found.", 404)

    # Verify environment belongs to the project.
    environment = db.scalar(
        select(EnvironmentModel).where(
            EnvironmentModel.id == environment_id,
            EnvironmentModel.project_id == project_id,
        )
    )

    if environment is None:
        raise ServiceError("not_found", "Run not found.", 404)

    # Verify run belongs to the project and environment.
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
    )

    if run is None:
        raise ServiceError("not_found", "Run not found.", 404)

    # Build results query with requirement titles.
    query = (
        select(ResultModel, Requirement.title)
        .join(
            Requirement,
            Requirement.id == ResultModel.requirement_id,
        )
        .where(
            ResultModel.project_id == project_id,
            ResultModel.analysis_run_id == run_id,
        )
    )

    # Cursor pagination.
    if page.cursor:
        try:
            cursor_id = uuid.UUID(page.cursor)
        except ValueError:
            raise ServiceError(
                "invalid_cursor",
                "Invalid pagination cursor.",
                422,
            )

        cursor_result = db.scalar(
            select(ResultModel).where(
                ResultModel.id == cursor_id,
                ResultModel.project_id == project_id,
                ResultModel.analysis_run_id == run_id,
            )
        )

        if cursor_result is None:
            raise ServiceError(
                "invalid_cursor",
                "Pagination cursor not found.",
                422,
            )

        query = query.where(ResultModel.id < cursor_id)

    # Newest first.
    query = query.order_by(ResultModel.id.desc())

    rows = db.execute(
        query.limit(page.limit + 1)
    ).all()

    has_more = len(rows) > page.limit
    rows = rows[:page.limit]

    result_ids = [result.id for result, _ in rows]

    # Fetch related data in batches.
    assessments = db.scalars(
        select(CriterionAssessment).where(
            CriterionAssessment.result_id.in_(result_ids)
        )
    ).all() if result_ids else []

    actions = db.scalars(
        select(Action).where(
            Action.result_id.in_(result_ids)
        ).order_by(Action.idx)
    ).all() if result_ids else []

    evidence_items = db.scalars(
        select(EvidenceModel).where(
            EvidenceModel.result_id.in_(result_ids)
        )
    ).all() if result_ids else []

    # Retrieve acceptance criterion text where it still exists.
    criterion_ids = {
        item.criterion_id
        for item in assessments
        if item.criterion_id is not None
    }

    criteria = db.scalars(
        select(AcceptanceCriterion).where(
            AcceptanceCriterion.id.in_(criterion_ids)
        )
    ).all() if criterion_ids else []

    criteria_by_id = {
        criterion.id: criterion
        for criterion in criteria
    }

    # Group related records by result.
    assessments_by_result = {}
    actions_by_result = {}
    evidence_by_result = {}

    for item in assessments:
        assessments_by_result.setdefault(
            item.result_id, []
        ).append(item)

    for item in actions:
        actions_by_result.setdefault(
            item.result_id, []
        ).append(item)

    for item in evidence_items:
        evidence_by_result.setdefault(
            item.result_id, []
        ).append(item)

    # Build API responses.
    items = []

    for result, requirement_title in rows:
        result_assessments = assessments_by_result.get(
            result.id, []
        )

        result_actions = actions_by_result.get(
            result.id, []
        )

        result_evidence = evidence_by_result.get(
            result.id, []
        )

        items.append(
            Result(
                id=str(result.id),
                run_id=str(result.analysis_run_id),
                requirement_id=str(result.requirement_id),
                requirement_title=requirement_title,
                verdict=result.verdict,
                classification=result.classification,
                observed_behavior=result.observed_behavior,

                criterion_assessments=[
                    CriterionAssessmentSchema(
                        criterion_id=str(item.criterion_id or ""),
                        criterion_text=(
                            criteria_by_id[item.criterion_id].text
                            if item.criterion_id in criteria_by_id
                            else ""
                        ),
                        verdict=item.verdict,
                        rationale=item.rationale,
                        source=item.source,
                        cited_evidence_ids=[],
                    )
                    for item in result_assessments
                ],

                actions=[
                    ActionSchema(
                        index=item.idx,
                        kind=item.kind,
                        description=item.description,
                        outcome=item.outcome,
                        evidence_id=(
                            str(item.evidence_id)
                            if item.evidence_id else None
                        ),
                    )
                    for item in result_actions
                ],

                evidence=[
                    EvidenceSchema(
                        id=str(item.id),
                        type=item.type,
                        media_type=item.media_type,
                        observation_id=item.observation_id,
                        sha256=item.sha256,
                        captured_at=item.captured_at,
                    )
                    for item in result_evidence
                ],

                duration_ms=result.duration_ms,
            )
        )

    return Page[Result](
        items=items,
        next_cursor=(
            str(rows[-1][0].id)
            if has_more and rows
            else None
        ),
    )

# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/results/{resid}",
    tags=["Analysis"],
    summary="Get one result, with its evidence",
    response_model=Result,
)
def get_result(context: ProjectAccess, eid: str, runid: str, resid: str, db: Db) -> Result:
    try:
        environment_id = uuid.UUID(eid)
        run_id = uuid.UUID(runid)
        result_id = uuid.UUID(resid)
        project_id = uuid.UUID(context.project_id)
    except ValueError:
        raise ServiceError("not_found", "Result not found.", 404)

    # Verify environment and run ownership.
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
    )

    if run is None:
        raise ServiceError("not_found", "Result not found.", 404)

    # Fetch the result within the authorized run.
    result = db.scalar(
        select(Result).where(
            Result.id == result_id,
            Result.analysis_run_id == run_id,
            Result.project_id == project_id,
        )
    )

    if result is None:
        raise ServiceError("not_found", "Result not found.", 404)

    # Fetch criterion assessments.
    assessments = db.scalars(
        select(CriterionAssessment).where(
            CriterionAssessment.result_id == result_id
        )
    ).all()

    # Fetch actions.
    actions = db.scalars(
        select(Action)
        .where(Action.result_id == result_id)
        .order_by(Action.idx)
    ).all()

    # Fetch evidence.
    evidence_items = db.scalars(
        select(Evidence)
        .where(Evidence.result_id == result_id)
        .order_by(Evidence.captured_at)
    ).all()

    return Result(
        id=str(result.id),
        run_id=str(result.analysis_run_id),
        requirement_id=str(result.requirement_id),
        requirement_title="",  # Populate from the saved requirement snapshot.
        verdict=result.verdict,
        classification=result.classification,
        observed_behavior=result.observed_behavior,
        criterion_assessments=[
            CriterionAssessment(
                criterion_id=str(a.criterion_id) if a.criterion_id else "",
                criterion_text="",  # Populate from the saved criterion snapshot.
                verdict=a.verdict,
                rationale=a.rationale,
                source=a.source,
                cited_evidence_ids=[],
            )
            for a in assessments
        ],
        actions=[
            Action(
                index=a.idx,
                kind=a.kind,
                description=a.description,
                outcome=a.outcome,
                evidence_id=str(a.evidence_id) if a.evidence_id else None,
            )
            for a in actions
        ],
        evidence=[
            Evidence(
                id=str(e.id),
                type=e.type,
                media_type=e.media_type,
                observation_id=e.observation_id,
                sha256=e.sha256,
                captured_at=e.captured_at,
            )
            for e in evidence_items
        ],
        duration_ms=result.duration_ms,
    )


# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/events",
    tags=["Analysis"],
    summary="Stream live run events",
    description=(
        "Server-sent events. Reconnect with Last-Event-ID to replay what was missed; "
        "refetch the run on completion rather than trusting the stream alone."
    ),
)
def stream_run_events(context: ProjectAccess, eid: str, runid: str, db: Db, 
last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,) -> None:
    # Validate IDs.
    try:
        project_id = uuid.UUID(context.project_id)
        environment_id = uuid.UUID(eid)
        run_id = uuid.UUID(runid)
    except ValueError:
        raise ServiceError("not_found", "Run not found.", 404)

    # Validate reconnect cursor.
    try:
        last_sequence = int(last_event_id) if last_event_id else 0
        if last_sequence < 0:
            raise ValueError
    except ValueError:
        raise ServiceError(
            "invalid_cursor",
            "Invalid Last-Event-ID.",
            422,
        )

    # Verify the run belongs to this project and environment.
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
    )

    if run is None:
        raise ServiceError("not_found", "Run not found.", 404)

    def event_stream():
        nonlocal last_sequence

        last_heartbeat = time.monotonic()

        yield "retry: 3000\n\n"

        while True:
            # Fetch events that have not yet been delivered.
            events = db.scalars(
                select(RunExecutionEvent)
                .where(
                    RunExecutionEvent.analysis_run_id == run_id,
                    RunExecutionEvent.sequence > last_sequence,
                )
                .order_by(RunExecutionEvent.sequence.asc())
                .limit(100)
            ).all()

            for event in events:
                payload = json.dumps(event.payload, default=str)

                yield (
                    f"id: {event.sequence}\n"
                    f"event: {event.event_type}\n"
                    f"data: {payload}\n\n"
                )

                last_sequence = event.sequence

            # Check whether execution has finished.
            current_status = db.scalar(
                select(AnalysisRun.status).where(
                    AnalysisRun.id == run_id,
                    AnalysisRun.project_id == project_id,
                )
            )

            if current_status in ("completed", "failed", "cancelled"):
                # All currently persisted events have been delivered.
                yield "event: stream_complete\ndata: {}\n\n"
                break

            # Send a heartbeat every 15 seconds.
            if time.monotonic() - last_heartbeat >= 15:
                yield ": heartbeat\n\n"
                last_heartbeat = time.monotonic()

            time.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Nishitha, WORK ON THIS
@app.get(
    "/projects/{pid}/environments/{eid}/runs/{runid}/ai-usage",
    tags=["Analysis"],
    summary="What a run cost",
    response_model=RunUsage,
    description="Pending is not zero. Cost may arrive after a run finishes and is final only once everything expected has.",
)
def run_usage(context: ProjectAccess, eid: str, runid: str, db: Db) -> RunUsage:
        # Validate IDs.
    try:
        project_id = uuid.UUID(context.project_id)
        environment_id = uuid.UUID(eid)
        run_id = uuid.UUID(runid)
    except ValueError:
        raise ServiceError("not_found", "Run not found.", 404)

    # Verify run belongs to this project and environment.
    run = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.id == run_id,
            AnalysisRun.project_id == project_id,
            AnalysisRun.environment_id == environment_id,
        )
    )

    if run is None:
        raise ServiceError("not_found", "Run not found.", 404)

    # Aggregate token usage.
    usage = db.execute(
        select(
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
        ).where(
            AIUsage.analysis_run_id == run_id,
            AIUsage.project_id == project_id,
        )
    ).one()

    input_tokens, output_tokens = usage

    # Calculate recorded USD costs.
    cost = db.scalar(
        select(func.sum(AIUsage.amount)).where(
            AIUsage.analysis_run_id == run_id,
            AIUsage.project_id == project_id,
            AIUsage.currency == "USD",
        )
    )

    # Finalization persistence has not been implemented yet.
    # Never claim a cost is final without confirmation.
    cost_status = "pending"

    return RunUsage(
        run_id=str(run.id),
        estimated_cost_usd=float(cost) if cost is not None else None,
        cost_status=cost_status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


# SRINIVAS, WORK ON THESE
@app.get(
    "/evidence/{eid}",
    tags=["Evidence"],
    summary="Fetch an evidence artifact",
    status_code=302,
    description="Redirects to a short-lived signed URL. Evidence is served by id, never by storage path.",
)
def get_evidence(user: CurrentUser, eid: str) -> None:
    raise todo("B6", "Evidence storage")


# ---------------------------------------------------------------------------
# Internal — aiservice only
#
# Three rules hold whatever the field shapes become: persist before publishing,
# deduplicate on the event id, and mark cost final only when the expected usage
# has actually arrived. Authenticated with the job-scoped credential BE issued
# at dispatch, not a shared key.
# ---------------------------------------------------------------------------


# SRINIVAS, WORK ON THESE
@app.post(
    "/internal/v1/runs/{runid}/execution-events",
    tags=["Internal"],
    summary="Receive execution events from aiservice",
    status_code=202,
    response_model=Acknowledged,
    description="Deduplicated on event_id and ordered by sequence. Persisted before being published to the live stream.",
)
def receive_execution_event(runid: str, body: ExecutionEvent) -> Acknowledged:
    raise todo("B6", "Execution event ingestion")


# SRINIVAS, WORK ON THESE
@app.post(
    "/internal/v1/runs/{runid}/ai-usage",
    tags=["Internal"],
    summary="Receive AI usage from aiservice",
    status_code=202,
    response_model=Acknowledged,
    description="Idempotent on usage_id. A revision replaces an estimate rather than adding a second charge.",
)
def receive_ai_usage(runid: str, body: AIUsageReport) -> Acknowledged:
    raise todo("B6", "Usage ingestion")


# SRINIVAS, WORK ON THESE
@app.post(
    "/internal/v1/runs/{runid}/ai-cost-finalizations",
    tags=["Internal"],
    summary="Close out a run's cost",
    status_code=202,
    response_model=Acknowledged,
    description="Cost becomes final only when the reported usage count matches. Run completion alone is not sufficient.",
)
def finalize_ai_cost(runid: str, body: CostFinalization) -> Acknowledged:
    raise todo("B6", "Cost finalization")
