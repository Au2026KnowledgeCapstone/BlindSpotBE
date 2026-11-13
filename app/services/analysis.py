"""Run lifecycle and durable dispatch, adapted from v2 approved snapshots."""
import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select, func

from app.core.config import get_settings
from app.core.errors import ServiceError
from app.core.urls import target_url
from app.models import AnalysisRun, Project, Environment, Requirement, Result, AIUsage, Action, Evidence
from app.models.integration import Dispatch, ResultDetail
from app.services.resources import uid, scoped, criteria, credential_cipher, paginate


def now():
    return datetime.now(timezone.utc)


def cipher():
    key = get_settings().dispatch_encryption_key
    if not key:
        raise ServiceError("unavailable", "Dispatch encryption is not configured.", 503)
    return Fernet(key.encode())


def validate_url(value):
    try:
        return target_url(value)
    except ValueError:
        raise ServiceError("validation_error", "Use an HTTP(S) URL without embedded credentials.", 422) from None


def create_run(db, context, eid, body, idempotency_key=None):
    settings = get_settings()
    if not settings.ai_service_url or not settings.ai_api_key or not settings.ai_callback_base_url:
        raise ServiceError("unavailable", "AI service dispatch is not configured.", 503)
    encryption = cipher()
    submission_key = None
    fingerprint = hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()
    if idempotency_key is not None:
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise ServiceError("validation_error", "Idempotency-Key must contain 1 to 128 nonblank characters.", 422)
        scope = [context.project_id, str(eid), context.user.user_id, idempotency_key]
        submission_key = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
    # Project lock serializes run numbering and submission across API workers.
    db.scalar(select(Project).where(Project.id == uid(context.project_id)).with_for_update())
    environment = scoped(db, Environment, context.project_id, eid, lock=True)
    if submission_key:
        previous = db.scalar(select(Dispatch).where(Dispatch.submission_key == submission_key))
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise ServiceError("conflict", "Idempotency-Key was reused with a different request.", 409)
            return run_out(db, db.get(AnalysisRun, previous.run_id))
    identifiers = [uid(value) for value in body.requirement_ids]
    if len(set(identifiers)) != len(identifiers):
        raise ServiceError("validation_error", "Select unique requirement IDs.", 422)
    snapshots = []
    for identifier in identifiers:
        requirement = scoped(db, Requirement, context.project_id, identifier, lock=True)
        acceptance = criteria(db, requirement)
        if requirement.approval_status != "approved" or not acceptance:
            raise ServiceError("conflict", "Only approved requirements with acceptance criteria can run.", 409)
        snapshots.append({"id": str(requirement.id), "title": requirement.title, "description": requirement.description,
                          "criteria": [{"id": str(c.id), "text": c.text} for c in acceptance]})
    number = (db.scalar(select(func.max(AnalysisRun.run_number)).where(AnalysisRun.project_id == uid(context.project_id))) or 0) + 1
    run = AnalysisRun(id=uuid4(), project_id=uid(context.project_id), environment_id=environment.id,
                      run_number=number, engine=settings.ai_engine, status="queued", requirement_snapshots=snapshots,
                      requested_by=uid(context.user.user_id), queued_at=now(), cancel_requested=False)
    db.add(run)
    db.flush()
    token, job = secrets.token_urlsafe(32), str(uuid4())
    credentials = {}
    if environment.encrypted_credentials:
        try:
            credentials = json.loads(credential_cipher().decrypt(environment.encrypted_credentials.encode()))
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("unavailable", "Environment credentials could not be decrypted.", 503) from None
    envelope = {"job_id": job, "run_id": str(run.id), "engine": run.engine,
                "target_url": validate_url(environment.base_url), "credentials": credentials,
                "requirements": snapshots, "callback_base_url": settings.ai_callback_base_url.rstrip('/'),
                "callback_token": token}
    validate_url(envelope["callback_base_url"])
    db.add(Dispatch(id=uuid4(), run_id=run.id, job_id=job, encrypted_envelope=encryption.encrypt(
        json.dumps(envelope).encode()).decode(), token_hash=hashlib.sha256(token.encode()).hexdigest(),
        status="pending", attempts=0, next_attempt_at=now(), last_sequence=0,
        submission_key=submission_key, request_fingerprint=fingerprint))
    db.commit()
    return run_out(db, run)


def run_out(db, row):
    count = db.scalar(select(func.count()).select_from(Action).join(Result, Action.result_id == Result.id).where(Result.analysis_run_id == row.id))
    return {"id": str(row.id), "run_number": row.run_number, "project_id": str(row.project_id),
            "environment_id": str(row.environment_id), "status": row.status, "engine": row.engine,
            "requirement_snapshots": row.requirement_snapshots, "requested_by": str(row.requested_by),
            "queued_at": row.queued_at, "started_at": row.started_at, "completed_at": row.completed_at,
            "action_count": count, "estimated_cost_usd": usage_out(db, row)["estimated_cost_usd"], "error": row.error}


def get_run(db, context, eid, runid, *, lock=False):
    scoped(db, Environment, context.project_id, eid)
    row = scoped(db, AnalysisRun, context.project_id, runid, lock=lock)
    if row.environment_id != uid(eid):
        raise ServiceError("not_found", "Run not found.", 404)
    return row


def list_runs(db, context, eid, page, status=None):
    scoped(db, Environment, context.project_id, eid)
    query = select(AnalysisRun).where(AnalysisRun.project_id == uid(context.project_id), AnalysisRun.environment_id == uid(eid))
    if status is not None:
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise ServiceError("validation_error", "Invalid run status.", 422)
        query = query.where(AnalysisRun.status == status)
    if page.cursor:
        try:
            number = int(page.cursor)
            if number < 1:
                raise ValueError()
        except ValueError:
            raise ServiceError("validation_error", "Invalid run cursor.", 422) from None
        query = query.where(AnalysisRun.run_number < number)
    rows = db.scalars(query.order_by(AnalysisRun.run_number.desc()).limit(page.limit + 1)).all()
    return {"items": [run_out(db, row) for row in rows[:page.limit]],
            "next_cursor": str(rows[page.limit - 1].run_number) if len(rows) > page.limit else None}


def cancel_run(db, context, eid, runid):
    run = get_run(db, context, eid, runid, lock=True)
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == run.id).with_for_update())
    if run.status in {"completed", "failed", "cancelled"}:
        return {"status": run.status}
    # Once a request has been attempted, intake may already have accepted it.
    if dispatch.attempts or dispatch.status != "pending":
        raise ServiceError("capability_unavailable", "aiservice does not expose remote cancellation.", 409)
    dispatch.status = "cancelled"
    run.status, run.completed_at, run.cancel_requested = "cancelled", now(), True
    db.commit()
    return {"status": "cancelled"}


def usage_out(db, run):
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == run.id))
    rows = db.scalars(select(AIUsage).where(AIUsage.analysis_run_id == run.id)).all()
    closed = bool(dispatch and dispatch.finalization)
    known = all(r.amount is not None and r.status != "reserved" for r in rows)
    return {"run_id": str(run.id), "estimated_cost_usd": sum((r.amount for r in rows), start=0) if closed and known else None,
            "cost_status": ("final" if known else "unknown") if closed else "pending",
            "input_tokens": sum(r.input_tokens for r in rows) if closed and all(r.input_tokens is not None for r in rows) else None,
            "output_tokens": sum(r.output_tokens for r in rows) if closed and all(r.output_tokens is not None for r in rows) else None}


def result_out(db, run, row):
    snapshot = next(s for s in run.requirement_snapshots if s["id"] == str(row.requirement_id))
    detail = db.get(ResultDetail, row.id)
    outcome = detail.outcome if detail else {}
    texts = {c["id"]: c["text"] for c in snapshot["criteria"]}
    return {"id": str(row.id), "run_id": str(run.id), "requirement_id": str(row.requirement_id),
            "requirement_title": snapshot["title"], "verdict": row.verdict, "classification": row.classification,
            "observed_behavior": row.observed_behavior, "duration_ms": row.duration_ms,
            "criterion_assessments": [{**v, "criterion_text": texts[v["criterion_id"]]} for v in outcome.get("criterion_verdicts", [])],
            "actions": outcome.get("actions", []), "evidence": [
                {"id": str(e.id), "type": e.type, "media_type": e.media_type, "observation_id": e.observation_id,
                 "sha256": e.sha256, "captured_at": e.captured_at}
                for e in db.scalars(select(Evidence).where(Evidence.result_id == row.id)).all()]}


def list_results(db, context, eid, runid, page):
    run = get_run(db, context, eid, runid)
    return paginate(db, select(Result).where(Result.analysis_run_id == run.id), Result, page, lambda row: result_out(db, run, row))


def get_result(db, context, eid, runid, resid):
    run = get_run(db, context, eid, runid)
    result = scoped(db, Result, context.project_id, resid)
    if result.analysis_run_id != run.id:
        raise ServiceError("not_found", "Result not found.", 404)
    return result_out(db, run, result)
