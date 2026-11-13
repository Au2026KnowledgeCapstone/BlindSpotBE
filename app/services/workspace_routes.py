"""Cookie-authenticated identity and project operations."""
import asyncio
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import AuthenticatedUser, current_user
from app.core.db import get_db
from app.core.deps import ProjectManage
from app.schemas.common import Page
from app.schemas.environments import Environment as EnvironmentOut, EnvironmentCreate
from app.schemas.common import Acknowledged
from app.schemas.identity import (
    Invitation as InvitationOut,
    InvitationCreate,
    Member,
    Notification,
    NotificationUpdate,
    Project as ProjectOut,
    ProjectCreate as ProjectCreateSchema,
    ProjectUpdate,
    UnreadCount,
)
from app.services.workspace_api import AuthError, rest

MAX_ENV_CREDENTIAL_BYTES = 16_384

router = APIRouter(tags=["Projects", "Identity"])


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationCreate(Body):
    name: str = Field(min_length=1, max_length=120)


class ApplicationOut(BaseModel):
    id: str
    project_id: str
    name: str
    created_at: datetime


class EnvironmentInput(EnvironmentCreate):
    application_id: UUID | None = None
    credential_reference: str | None = Field(default=None, max_length=200)


class ScanCreate(Body):
    environment_id: UUID


class ScanRequestOut(BaseModel):
    id: str
    project_id: str
    environment_id: str
    requested_by: str
    status: Literal["queued"]
    created_at: datetime


class TestResultOut(BaseModel):
    id: str
    project_id: str
    scan_id: str
    name: str
    status: Literal["passed", "failed", "skipped"]
    summary: str
    created_at: datetime


def token(request: Request) -> str:
    return request.cookies.get(request.app.state.auth_settings.access_cookie, "")


def _rows(value) -> list[dict]:
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    if isinstance(value, dict):
        return [value]
    raise AuthError(503, "Invalid workspace service response")


def _one(value) -> dict:
    rows = _rows(value)
    if len(rows) != 1:
        raise AuthError(503, "Invalid workspace service response")
    return rows[0]


def _page(rows: list[dict], limit: int, cursor_field: str = "id") -> dict:
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": rows, "next_cursor": rows[-1][cursor_field] if more and rows else None}


def _size(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise AuthError(422, "Page limit must be between 1 and 100")
    return limit


def _project_row(row: dict, user: AuthenticatedUser) -> dict:
    if row.get("owner_id") == user.user_id:
        row["role"] = "owner"
    else:
        row["role"] = row.get("membership_role", "member")
    row.pop("membership_role", None)
    return row


def _environment_out(row: dict) -> dict:
    return {
        "id": str(row["id"]), "project_id": str(row["project_id"]), "name": row["name"],
        "kind": row["kind"], "base_url": row["base_url"],
        "has_credentials": bool(row.get("encrypted_credentials")),
        "revision": row.get("revision", 1), "verified_at": row.get("verified_at"),
        "created_at": row["created_at"],
    }


def _project_select() -> str:
    return "id,name,description,owner_id,created_at"


@router.get("/projects", response_model=Page[ProjectOut], tags=["Projects"])
async def list_projects(request: Request, response: Response, limit: int = 50, cursor: UUID | None = None, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    params = {"select": _project_select(), "order": "id.asc", "limit": str(limit + 1)}
    if cursor:
        params["id"] = f"gt.{cursor}"
    rows = _rows(await rest(request, token(request), "GET", "projects", params=params))
    project_ids = [str(row["id"]) for row in rows]
    if project_ids:
        memberships = _rows(await rest(request, token(request), "GET", "project_members", params={"select": "project_id,role", "user_id": f"eq.{user.user_id}", "project_id": f"in.({','.join(project_ids)})", "limit": str(len(project_ids))}))
        roles = {r["project_id"]: r["role"] for r in memberships}
        for row in rows:
            row["membership_role"] = roles.get(row["id"])
            _project_row(row, user)
    return _page(rows, limit)


@router.get("/projects/{pid}", response_model=ProjectOut, tags=["Projects"])
async def get_project(pid: UUID, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    rows = _rows(await rest(request, token(request), "GET", "projects", params={"id": f"eq.{pid}", "select": _project_select(), "limit": "1"}))
    if not rows:
        raise AuthError(404, "Project not found")
    row = rows[0]
    memberships = _rows(await rest(request, token(request), "GET", "project_members", params={"select": "role", "project_id": f"eq.{pid}", "user_id": f"eq.{user.user_id}", "limit": "1"}))
    row["membership_role"] = "owner" if row["owner_id"] == user.user_id else (memberships[0]["role"] if memberships else None)
    result = _project_row(row, user)
    if result["role"] is None:
        raise AuthError(404, "Project not found")
    return result


@router.post("/projects", status_code=201, response_model=ProjectOut, tags=["Projects"])
async def create_project(body: ProjectCreateSchema, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    result = _one(await rest(request, token(request), "RPC", "rpc/create_project", body={"p_name": body.name, "p_description": body.description}))
    result["role"] = "owner"
    return result


@router.patch("/projects/{pid}", response_model=ProjectOut, tags=["Projects"])
async def update_project(pid: UUID, body: ProjectUpdate, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    if project["role"] not in {"owner", "admin"}:
        raise AuthError(403, "Project admin required")
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return project
    rows = _rows(await rest(request, token(request), "PATCH", "projects", params={"id": f"eq.{pid}", "select": _project_select()}, body=changes))
    if not rows:
        raise AuthError(404, "Project not found")
    row = rows[0]
    row["membership_role"] = project["role"]
    return _project_row(row, user)


@router.delete("/projects/{pid}", status_code=204, tags=["Projects"])
async def delete_project(pid: UUID, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    if project["role"] != "owner":
        raise AuthError(403, "Project owner required")
    await rest(request, token(request), "DELETE", "projects", params={"id": f"eq.{pid}"})


@router.get("/projects/{pid}/workspace", tags=["Projects"])
async def project_workspace(pid: UUID, request: Request, response: Response, limit: int = 50, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    common = {"project_id": f"eq.{pid}", "limit": str(limit)}
    project = await get_project(pid, request, response, user)
    applications, environments, scans, results = await asyncio.gather(
        rest(request, token(request), "GET", "applications", params={**common, "select": "id,project_id,name,created_at", "order": "id.asc"}),
        rest(request, token(request), "GET", "environments", params={**common, "select": "id,project_id,name,kind,base_url,encrypted_credentials,revision,verified_at,created_at", "order": "id.asc"}),
        rest(request, token(request), "GET", "scans", params={**common, "select": "id,project_id,environment_id,requested_by,status,created_at", "order": "id.desc"}),
        rest(request, token(request), "GET", "test_results", params={**common, "select": "id,project_id,scan_id,name,status,summary,created_at", "order": "id.desc"}),
    )
    application_rows = _rows(applications)
    environment_rows = [_environment_out(row) for row in _rows(environments)]
    scan_rows = _rows(scans)
    result_rows = _rows(results)
    return {
        "applications": _page(application_rows, limit),
        "environments": _page(environment_rows, limit),
        "scans": _page(scan_rows, limit),
        "results": _page(result_rows, limit),
    }


@router.post("/projects/{pid}/applications", status_code=201, response_model=ApplicationOut, tags=["Projects"])
async def create_application(pid: UUID, body: ApplicationCreate, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    if project["role"] not in {"owner", "admin"}:
        raise AuthError(403, "Project admin required")
    rows = _rows(await rest(request, token(request), "POST", "applications", body={"project_id": str(pid), "name": body.name}))
    if len(rows) != 1:
        raise AuthError(503, "Invalid workspace service response")
    return rows[0]


@router.post("/projects/{pid}/environments", status_code=201, response_model=EnvironmentOut, tags=["Projects"])
async def create_environment(pid: UUID, body: EnvironmentInput, request: Request, response: Response, context: ProjectManage, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    if context.project_id != str(pid):
        raise AuthError(404, "Project not found")
    credentials = body.credentials
    encrypted = None
    if credentials is not None:
        import json
        from cryptography.fernet import Fernet
        from app.core.config import get_settings
        raw = json.dumps(credentials, separators=(",", ":" )).encode()
        if len(raw) > MAX_ENV_CREDENTIAL_BYTES:
            raise AuthError(422, "Credentials exceed the maximum size")
        key = get_settings().environment_credential_encryption_key
        if not key:
            raise AuthError(503, "Environment credential encryption is unavailable")
        try:
            encrypted = Fernet(key.encode()).encrypt(raw).decode()
        except (TypeError, ValueError):
            raise AuthError(503, "Environment credential encryption is unavailable") from None
    result = db.execute(text("""
        INSERT INTO public.environments(project_id, application_id, name, kind, base_url, credential_reference, encrypted_credentials)
        VALUES (:project_id, :application_id, :name, :kind, :base_url, :credential_reference, :encrypted_credentials)
        RETURNING id, project_id, name, kind, base_url, encrypted_credentials, revision, verified_at, created_at
    """), {
        "project_id": pid, "application_id": body.application_id, "name": body.name, "kind": body.kind,
        "base_url": body.base_url, "credential_reference": body.credential_reference,
        "encrypted_credentials": encrypted,
    }).mappings().one()
    db.commit()
    return _environment_out(dict(result))


@router.post("/projects/{pid}/scans", status_code=202, response_model=ScanRequestOut, tags=["Projects"])
async def create_scan(pid: UUID, body: ScanCreate, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    environment = _rows(await rest(request, token(request), "GET", "environments", params={"id": f"eq.{body.environment_id}", "project_id": f"eq.{pid}", "select": "id", "limit": "1"}))
    if not environment:
        raise AuthError(404, "Environment not found")
    if project["role"] not in {"owner", "admin", "member"}:
        raise AuthError(404, "Project not found")
    rows = _rows(await rest(request, token(request), "POST", "scans", body={"project_id": str(pid), "environment_id": str(body.environment_id)}))
    if len(rows) != 1:
        raise AuthError(503, "Invalid workspace service response")
    row = rows[0]
    if row.get("status") != "queued":
        raise AuthError(503, "Invalid queued scan response")
    return row


@router.get("/projects/{pid}/members", response_model=Page[Member], tags=["Projects"])
async def list_members(pid: UUID, request: Request, response: Response, limit: int = 50, cursor: UUID | None = None, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    params = {"project_id": f"eq.{pid}", "select": "user_id,role", "order": "user_id.asc", "limit": str(limit + 1)}
    if cursor:
        params["user_id"] = f"gt.{cursor}"
    rows = _rows(await rest(request, token(request), "GET", "project_members", params=params))
    user_ids = [row["user_id"] for row in rows]
    profiles = _rows(await rest(request, token(request), "GET", "profiles", params={"select": "user_id,display_name", "user_id": f"in.({','.join(user_ids)})", "limit": str(len(user_ids))})) if user_ids else []
    names = {row["user_id"]: row["display_name"] for row in profiles}
    members = [{"user_id": row["user_id"], "role": row["role"], "display_name": names.get(row["user_id"], "")} for row in rows]
    return _page(members, limit, "user_id")


@router.delete("/projects/{pid}/members/{uid}", status_code=204, tags=["Projects"])
async def remove_member(pid: UUID, uid: UUID, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    if project["role"] not in {"owner", "admin"}:
        raise AuthError(403, "Project admin required")
    rows = _rows(await rest(request, token(request), "GET", "project_members", params={"project_id": f"eq.{pid}", "user_id": f"eq.{uid}", "select": "role", "limit": "1"}))
    if not rows:
        raise AuthError(404, "Member not found")
    if rows[0]["role"] == "owner":
        raise AuthError(403, "Cannot remove the project owner")
    await rest(request, token(request), "DELETE", "project_members", params={"project_id": f"eq.{pid}", "user_id": f"eq.{uid}"})


@router.get("/invitations", response_model=Page[InvitationOut], tags=["Projects"])
async def my_invitations(request: Request, response: Response, limit: int = 50, cursor: UUID | None = None, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    params = {"email": f"eq.{user.email.lower()}", "accepted_at": "is.null", "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}", "select": "id,project_id,email,role,invited_by,expires_at,created_at", "order": "id.asc", "limit": str(limit + 1)}
    if cursor:
        params["id"] = f"gt.{cursor}"
    return _page(_rows(await rest(request, token(request), "GET", "invitations", params=params)), limit)


@router.get("/projects/{pid}/invitations", response_model=Page[InvitationOut], tags=["Projects"])
async def list_invitations(pid: UUID, request: Request, response: Response, limit: int = 50, cursor: UUID | None = None, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    project = await get_project(pid, request, response, user)
    if project["role"] not in {"owner", "admin"}:
        raise AuthError(403, "Project admin required")
    params = {"project_id": f"eq.{pid}", "accepted_at": "is.null", "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}", "select": "id,project_id,email,role,invited_by,expires_at,created_at", "order": "id.asc", "limit": str(limit + 1)}
    if cursor:
        params["id"] = f"gt.{cursor}"
    return _page(_rows(await rest(request, token(request), "GET", "invitations", params=params)), limit)


@router.post("/projects/{pid}/invitations", status_code=201, response_model=InvitationOut, tags=["Projects"])
async def create_invitation(pid: UUID, body: InvitationCreate, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return _one(await rest(request, token(request), "RPC", "rpc/invite_member", body={"p_project_id": str(pid), "p_email": body.email, "p_role": body.role}))


@router.post("/invitations/{iid}/accept", response_model=Member, tags=["Projects"])
async def accept_invitation(iid: UUID, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    row = _one(await rest(request, token(request), "RPC", "rpc/accept_invitation", body={"p_invitation_id": str(iid)}))
    return {"user_id": row["user_id"], "role": row["role"], "display_name": ""}


@router.get("/notifications", response_model=Page[Notification], tags=["Identity"])
async def notifications(request: Request, response: Response, limit: int = 30, cursor: UUID | None = None, unread: bool = False, user: AuthenticatedUser = Depends(current_user)):
    limit = _size(limit)
    response.headers["Cache-Control"] = "no-store"
    params = {"select": "id,project_id,message,read_at,created_at", "order": "id.desc", "limit": str(limit + 1)}
    if cursor:
        params["id"] = f"lt.{cursor}"
    if unread:
        params["read_at"] = "is.null"
    return _page(_rows(await rest(request, token(request), "GET", "notifications", params=params)), limit)


@router.get("/notifications/unread-count", response_model=UnreadCount, tags=["Identity"])
async def unread_count(request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    await rest(request, token(request), "GET", "notifications", params={"select": "id", "read_at": "is.null", "limit": "1"}, count="exact")
    content_range = getattr(request.state, "upstream_content_range", None)
    total = content_range.rsplit("/", 1)[-1] if content_range else ""
    if not total.isdecimal():
        raise AuthError(503, "Invalid notification count response")
    return {"unread": int(total)}


@router.patch("/notifications/{nid}", response_model=Notification, tags=["Identity"])
async def mark_read(nid: UUID, body: NotificationUpdate, request: Request, response: Response, user: AuthenticatedUser = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    rows = _rows(await rest(request, token(request), "PATCH", "notifications", params={"id": f"eq.{nid}", "select": "id,project_id,message,read_at,created_at"}, body={"read_at": datetime.now(timezone.utc).isoformat() if body.read else None}))
    if not rows:
        raise AuthError(404, "Notification not found")
    return rows[0]
