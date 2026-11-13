"""Project-scoped requirements and environments, adapted from v2 semantics."""
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy import select, or_, delete

from app.core.config import get_settings
from app.core.errors import ServiceError
from app.models import Requirement, AcceptanceCriterion, Environment, Result, AnalysisRun


def uid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ServiceError("not_found", "Resource not found.", 404) from None


def scoped(db, model, project_id, resource_id, *, lock=False):
    query = select(model).where(model.id == uid(resource_id), model.project_id == uid(project_id))
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ServiceError("not_found", "Resource not found.", 404)
    return row


def paginate(db, query, model, page, serialize):
    if page.cursor:
        query = query.where(model.id > uid(page.cursor))
    rows = db.scalars(query.order_by(model.id).limit(page.limit + 1)).all()
    return {"items": [serialize(row) for row in rows[:page.limit]],
            "next_cursor": str(rows[page.limit - 1].id) if len(rows) > page.limit else None}


def criteria(db, row):
    return db.scalars(select(AcceptanceCriterion).where(
        AcceptanceCriterion.requirement_id == row.id).order_by(AcceptanceCriterion.position, AcceptanceCriterion.id)).all()


def requirement_out(db, row):
    latest = db.execute(select(Result, AnalysisRun).join(AnalysisRun, Result.analysis_run_id == AnalysisRun.id).where(
        Result.requirement_id == row.id, AnalysisRun.completed_at.is_not(None)).order_by(
        AnalysisRun.completed_at.desc(), AnalysisRun.id.desc()).limit(1)).first()
    return {"id": str(row.id), "project_id": str(row.project_id), "title": row.title,
            "description": row.description, "category": row.category, "priority": row.priority,
            "approval_status": row.approval_status, "source": row.source,
            "acceptance_criteria": [{"id": str(c.id), "text": c.text, "position": c.position} for c in criteria(db, row)],
            "created_at": row.created_at, "updated_at": row.updated_at,
            "latest_result": {"run_id": str(latest[1].id), "verdict": latest[0].verdict,
                              "completed_at": latest[1].completed_at} if latest else None}


def list_requirements(db, context, page, q=None, **filters):
    query = select(Requirement).where(Requirement.project_id == uid(context.project_id))
    for key, value in filters.items():
        if value is not None:
            query = query.where(getattr(Requirement, key) == value)
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        matching = select(AcceptanceCriterion.requirement_id).where(AcceptanceCriterion.text.ilike(pattern, escape='\\'))
        predicates = [Requirement.title.ilike(pattern, escape='\\'), Requirement.description.ilike(pattern, escape='\\'), Requirement.id.in_(matching)]
        try:
            predicates.append(Requirement.id == UUID(q))
        except ValueError:
            pass
        query = query.where(or_(*predicates))
    return paginate(db, query, Requirement, page, lambda row: requirement_out(db, row))


def reconcile(db, row, values):
    existing = {str(c.id): c for c in criteria(db, row)}
    seen = set()
    for index, value in enumerate(values):
        key = str(uid(value.id)) if value.id else str(uuid4())
        if key in seen or (value.id and key not in existing) or not value.text.strip():
            raise ServiceError("validation_error", "Criteria must be nonblank with unique IDs belonging to this requirement.", 422)
        seen.add(key)
        criterion = existing.get(key)
        if criterion is None:
            criterion = AcceptanceCriterion(id=UUID(key), project_id=row.project_id, requirement_id=row.id)
            db.add(criterion)
        criterion.text, criterion.position = value.text.strip(), index
    for key, criterion in existing.items():
        if key not in seen:
            db.delete(criterion)


def create_requirement(db, context, body):
    if not body.title.strip():
        raise ServiceError("validation_error", "Title must not be blank.", 422)
    row = Requirement(id=uuid4(), project_id=uid(context.project_id), source={"kind": "manual"},
                      approval_status="draft", **body.model_dump(exclude={"acceptance_criteria"}))
    db.add(row)
    db.flush()
    reconcile(db, row, body.acceptance_criteria)
    db.commit()
    return requirement_out(db, row)


def update_requirement(db, context, rid, body):
    row = scoped(db, Requirement, context.project_id, rid, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()) or ("title" in changes and not changes["title"].strip()):
        raise ServiceError("validation_error", "Requirement fields cannot be null or blank.", 422)
    changed = any(getattr(row, k) != v for k, v in changes.items() if k != "acceptance_criteria")
    if "acceptance_criteria" in changes:
        old = [(str(c.id), c.text) for c in criteria(db, row)]
        new = [(c.id, c.text.strip()) for c in body.acceptance_criteria]
        changed = changed or old != new
        reconcile(db, row, body.acceptance_criteria)
    for key, value in changes.items():
        if key != "acceptance_criteria":
            setattr(row, key, value)
    if changed:
        row.approval_status = "draft"
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return requirement_out(db, row)


def approve_requirement(db, context, rid, body):
    row = scoped(db, Requirement, context.project_id, rid, lock=True)
    if body.approved and (row.approval_status == "needs_clarification" or not criteria(db, row)):
        raise ServiceError("conflict", "Resolve clarification and supply acceptance criteria before approval.", 409)
    row.approval_status = "approved" if body.approved else "draft"
    db.commit()
    return requirement_out(db, row)


def delete_requirement(db, context, rid):
    row = scoped(db, Requirement, context.project_id, rid, lock=True)
    # Historical results keep their requirement FK; deleting history is never implicit.
    if db.scalar(select(Result.id).where(Result.requirement_id == row.id).limit(1)):
        raise ServiceError("conflict", "A requirement with execution history cannot be deleted.", 409)
    active = db.scalars(select(AnalysisRun).where(AnalysisRun.project_id == row.project_id,
        AnalysisRun.status.in_(["queued", "running"]))).all()
    if any(any(s["id"] == str(row.id) for s in run.requirement_snapshots) for run in active):
        raise ServiceError("conflict", "A requirement selected by an active run cannot be deleted.", 409)
    db.delete(row)
    db.commit()


def environment_out(row):
    return {"id": str(row.id), "project_id": str(row.project_id), "name": row.name, "kind": row.kind,
            "base_url": row.base_url, "has_credentials": bool(row.encrypted_credentials),
            "revision": row.revision, "verified_at": row.verified_at, "created_at": row.created_at}


def credential_cipher():
    key = get_settings().environment_credential_encryption_key
    if not key:
        raise ServiceError("unavailable", "Credential encryption is not configured.", 503)
    return Fernet(key.encode())


def update_environment(db, context, eid, body):
    row = scoped(db, Environment, context.project_id, eid, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for k, v in changes.items() if k != "credentials"):
        raise ServiceError("validation_error", "Environment fields cannot be null.", 422)
    invalidates = any(k in changes and getattr(row, k) != changes[k] for k in ("base_url",)) or "credentials" in changes
    if "credentials" in changes:
        values = changes.pop("credentials")
        raw = json.dumps(values, separators=(",", ":")).encode()
        if len(raw) > 16384:
            raise ServiceError("validation_error", "Credentials exceed the maximum size.", 422)
        row.encrypted_credentials = credential_cipher().encrypt(raw).decode() if values is not None else None
    for key, value in changes.items():
        setattr(row, key, value)
    if invalidates:
        row.verified_at = None
        row.revision += 1
    db.commit()
    return environment_out(row)
