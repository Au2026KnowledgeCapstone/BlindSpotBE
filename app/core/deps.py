"""Shared route dependencies.

The project checks here are the only thing standing between a user and another
project's data: BE does not rely on Supabase RLS, so authorization lives in one
place and every project-scoped route must depend on it. A route that forgets is
a data leak, not a bug — which is why this is a dependency rather than a line
each handler is trusted to write.
"""
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Path, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, current_user
from app.core.db import get_db
from app.core.errors import ServiceError

Role = Literal["owner", "admin", "member"]

# Ownership is recorded twice in the existing schema: projects.owner_id and a
# project_members row with role 'owner'. create_project writes both, and
# app_private.can_access ORs them, so this mirrors that rather than trusting
# either alone.
_MEMBERSHIP_SQL = text(
    """
    SELECT CASE
             WHEN p.owner_id = :user_id THEN 'owner'
             WHEN om.role IN ('owner', 'admin') THEN 'admin'
             ELSE m.role
           END AS role
    FROM public.projects p
    LEFT JOIN public.project_members m
      ON m.project_id = p.id AND m.user_id = :user_id
    LEFT JOIN public.organization_members om
      ON om.organization_id = p.organization_id AND om.user_id = :user_id
    WHERE p.id = :project_id
      AND (p.owner_id = :user_id OR m.user_id IS NOT NULL OR om.role IN ('owner', 'admin'))
    """
)


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    user: AuthenticatedUser
    role: Role


def _resolve(db: Session, project_id: str, user: AuthenticatedUser) -> ProjectContext:
    # 404 rather than 403, always. A 403 tells someone who cannot see a project
    # that it exists, which is itself a disclosure.
    try:
        row = db.execute(
            _MEMBERSHIP_SQL, {"project_id": project_id, "user_id": user.user_id}
        ).first()
    except Exception as exc:  # malformed uuid, or the table is unreachable
        raise ServiceError("not_found", "Project not found.", status_code=404) from exc

    if row is None or row.role is None:
        raise ServiceError("not_found", "Project not found.", status_code=404)
    return ProjectContext(project_id=project_id, user=user, role=row.role)


def project_access(
    pid: Annotated[str, Path(description="Project id.")],
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectContext:
    """Membership of any kind. Raises 404 when the caller is not a member."""
    return _resolve(db, pid, user)


def project_manage(
    context: Annotated[ProjectContext, Depends(project_access)],
) -> ProjectContext:
    """Owner or admin only. Mirrors app_private.can_manage."""
    if context.role not in ("owner", "admin"):
        raise ServiceError("forbidden", "This action requires project admin rights.", status_code=403)
    return context


@dataclass(frozen=True)
class Pagination:
    cursor: str | None
    limit: int


def pagination(
    cursor: Annotated[str | None, Query(description="Opaque cursor from a previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size. Max 100.")] = 50,
) -> Pagination:
    return Pagination(cursor=cursor, limit=limit)


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]
ProjectAccess = Annotated[ProjectContext, Depends(project_access)]
ProjectManage = Annotated[ProjectContext, Depends(project_manage)]
Paged = Annotated[Pagination, Depends(pagination)]
Db = Annotated[Session, Depends(get_db)]
