"""Transactional, replay-safe ingestion of the aiservice A1 protocol."""
import hashlib
import hmac
import json
from decimal import Decimal
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, func

from app.core.errors import ServiceError
from app.models import AnalysisRun, Result, Action, AIUsage, Notification, Requirement
from app.models.integration import Dispatch, Callback, ResultDetail
from app.services.resources import uid
from app.schemas.runs import Classification, Action as ActionSpec
from app.services.analysis import now


class Assessment(BaseModel):
    criterion_id: str
    verdict: Literal["pass", "fail", "inconclusive"]
    rationale: str
    cited_evidence_ids: list[str]
    source: Literal["ai", "objective", "engine"]


class Outcome(BaseModel):
    verdict: Literal["pass", "fail", "inconclusive"]
    classification: Classification
    observed_behavior: str
    criterion_verdicts: list[Assessment]
    actions: list[ActionSpec]


def conflict(message):
    raise ServiceError("callback_conflict", message, 409)


def authenticate(db, runid, authorization):
    # Lock run first everywhere to serialize callbacks, dispatch and cancellation.
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == uid(runid)).with_for_update())
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == uid(runid)).with_for_update())
    token = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else ""
    if not run or not dispatch or not token or not hmac.compare_digest(dispatch.token_hash, hashlib.sha256(token.encode()).hexdigest()):
        raise ServiceError("unauthorized", "Invalid callback credential.", 401)
    if dispatch.status == "cancelled":
        conflict("Run was cancelled before dispatch.")
    return run, dispatch


def duplicate(db, run, kind, body):
    prior = db.scalar(select(Callback).where(Callback.event_id == body.event_id))
    if prior:
        if prior.run_id != run.id or prior.kind != kind or prior.payload != body.model_dump(mode="json"):
            conflict("An event ID was reused with a different payload.")
        return True
    return False


def remember(db, run, kind, body, sequence=None):
    position = (db.scalar(select(func.max(Callback.position)).where(Callback.run_id == run.id)) or 0) + 1
    db.add(Callback(id=uuid4(), run_id=run.id, event_id=body.event_id, kind=kind, position=position,
                    sequence=sequence, payload=body.model_dump(mode="json")))
    db.commit()
    return {"status": "accepted"}


def execution(db, runid, authorization, body):
    run, dispatch = authenticate(db, runid, authorization)
    if body.job_id != dispatch.job_id:
        conflict("Job does not belong to this run.")
    if duplicate(db, run, "execution", body):
        return {"status": "accepted"}
    if body.sequence <= dispatch.last_sequence:
        conflict("Execution sequence must increase.")
    terminal = run.status in {"completed", "failed", "cancelled"}
    if terminal:
        conflict("A terminal run cannot receive new execution events.")
    if body.type == "requirement.completed":
        save_result(db, run, body.payload)
    else:
        status = {"job.running": "running", "job.finished": "completed", "job.failed": "failed", "job.cancelled": "cancelled"}[body.type]
        if body.payload.get("status") != body.type.split('.')[1]:
            conflict("Execution status does not match event type.")
        if status == "completed":
            db.flush()
            completed = db.scalars(select(Result).where(Result.analysis_run_id == run.id)).all()
            if len(completed) != len(run.requirement_snapshots):
                conflict("Run cannot complete before every requirement has an outcome.")
        run.status = status
        if status == "running":
            run.started_at = body.occurred_at
        else:
            run.completed_at = body.occurred_at
            # Keep arbitrary executor error text out of user-facing run metadata.
            run.error = "Executor failed." if status == "failed" else None
            db.add(Notification(id=uuid4(), user_id=run.requested_by, project_id=run.project_id,
                                message=f"Run #{run.run_number} {status}.", created_at=now()))
    dispatch.last_sequence = body.sequence
    return remember(db, run, "execution", body, body.sequence)


def save_result(db, run, payload):
    if payload.get("run_id") != str(run.id):
        conflict("Outcome run does not match callback run.")
    snapshot = next((s for s in run.requirement_snapshots if s["id"] == payload.get("requirement_id")), None)
    if snapshot is None:
        conflict("Outcome requirement is not in the immutable run snapshot.")
    try:
        outcome = Outcome.model_validate(payload.get("outcome"))
    except ValidationError:
        raise ServiceError("validation_error", "Invalid requirement outcome.", 422) from None
    expected = {c["id"] for c in snapshot["criteria"]}
    observed = [c.criterion_id for c in outcome.criterion_verdicts]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        conflict("Outcome must assess every snapshotted criterion exactly once.")
    if len({a.index for a in outcome.actions}) != len(outcome.actions):
        conflict("Action indexes must be unique.")
    if db.scalar(select(Result.id).where(Result.analysis_run_id == run.id, Result.requirement_id == uid(snapshot["id"]))):
        conflict("Requirement already has an outcome.")
    # A running snapshot cannot be orphaned by deleting its source requirement.
    if not db.get(Requirement, uid(snapshot["id"])):
        conflict("Requirement was removed while execution was pending.")
    result = Result(id=uuid4(), project_id=run.project_id, analysis_run_id=run.id,
                    requirement_id=uid(snapshot["id"]), verdict=outcome.verdict, classification=outcome.classification,
                    observed_behavior=outcome.observed_behavior, duration_ms=0)
    db.add(result)
    db.flush()
    db.add(ResultDetail(result_id=result.id, outcome=outcome.model_dump()))
    for action in outcome.actions:
        db.add(Action(id=uuid4(), result_id=result.id, idx=action.index, kind=action.kind,
                      description=action.description, outcome=action.outcome))


def usage(db, runid, authorization, body):
    run, dispatch = authenticate(db, runid, authorization)
    if body.job_id != dispatch.job_id:
        conflict("Job does not belong to this run.")
    if duplicate(db, run, "usage", body):
        return {"status": "accepted"}
    if dispatch.finalization:
        conflict("Cost session is already closed.")
    if dispatch.cost_session_id and dispatch.cost_session_id != body.cost_session_id:
        conflict("Unexpected cost session.")
    if (body.revision == 1) != (body.status == "reserved"):
        conflict("Usage revision and status do not agree.")
    if "reserved_at" not in body.timestamps or (body.revision == 2 and "finalized_at" not in body.timestamps):
        conflict("Required usage timestamps are missing.")
    row = db.scalar(select(AIUsage).where(AIUsage.usage_id == body.usage_id))
    if row and (row.analysis_run_id != run.id or row.job_id != body.job_id or row.cost_session_id != body.cost_session_id):
        conflict("Usage ID belongs to a different job/session.")
    if row and body.revision <= row.revision:
        # Same revision with another event ID is only valid for an identical value.
        if body.revision == row.revision and (row.status != body.status or row.tokens != body.tokens.model_dump() or row.amount != body.amount):
            conflict("Usage revision was reused with changed values.")
        return remember(db, run, "usage", body)
    if row is None:
        row = AIUsage(id=uuid4(), project_id=run.project_id, analysis_run_id=run.id, usage_id=body.usage_id)
        db.add(row)
    for key in ("event_id", "revision", "cost_session_id", "job_id", "attempt", "provider", "model", "operation", "amount", "currency", "status"):
        setattr(row, key, getattr(body, key))
    row.tokens = body.tokens.model_dump()
    row.input_tokens, row.output_tokens = body.tokens.input, body.tokens.output
    row.occurred_at = body.timestamps.get("finalized_at", body.timestamps["reserved_at"])
    dispatch.cost_session_id = body.cost_session_id
    return remember(db, run, "usage", body)


def usage_digest(rows):
    items = [{"usage_id": r.usage_id, "revision": r.revision, "status": r.status, "tokens": r.tokens,
              "amount": str(r.amount.quantize(Decimal("0.000000000001"))) if r.amount is not None else None,
              "currency": r.currency} for r in sorted(rows, key=lambda row: row.usage_id)]
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def finalize(db, runid, authorization, body):
    run, dispatch = authenticate(db, runid, authorization)
    if duplicate(db, run, "finalization", body):
        return {"status": "accepted"}
    if dispatch.finalization:
        conflict("Cost session is already closed.")
    if dispatch.cost_session_id and dispatch.cost_session_id != body.cost_session_id:
        conflict("Unexpected cost session.")
    rows = db.scalars(select(AIUsage).where(AIUsage.analysis_run_id == run.id, AIUsage.cost_session_id == body.cost_session_id)).all()
    if any(r.status == "reserved" for r in rows) or len(rows) != body.final_usage_count or usage_digest(rows) != body.final_usage_digest:
        # A retry can repair missing delivery; receiver has committed nothing.
        raise ServiceError("usage_pending", "Final usage count or digest does not match.", 503)
    dispatch.cost_session_id = body.cost_session_id
    dispatch.finalization = body.model_dump(mode="json")
    return remember(db, run, "finalization", body)
