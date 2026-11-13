"""Real PostgreSQL service/API tests. Use a disposable BLINDSPOT_TEST_DATABASE_URL."""
import hashlib
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

import main
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import ProjectContext, project_access, project_manage, Pagination
from app.core.errors import ServiceError
from app.models import Project, Environment, Requirement, Result, AIUsage, Notification, AnalysisRun
from app.models.integration import Dispatch, Callback
from app.schemas.requirements import RequirementCreate, RequirementUpdate, ApprovalRequest
from app.schemas.runs import RunCreate
from app.schemas.internal import AIUsageReport
from app.services import resources, analysis, callbacks
from app.services.dispatch import dispatch_once


@pytest.fixture
def setup(monkeypatch):
    url = os.environ.get("BLINDSPOT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set BLINDSPOT_TEST_DATABASE_URL to a migrated disposable PostgreSQL database")
    engine = create_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    sessions = sessionmaker(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    db = sessions()
    monkeypatch.setenv("AI_SERVICE_URL", "http://executor.test")
    monkeypatch.setenv("AI_API_KEY", "intake-secret")
    monkeypatch.setenv("AI_CALLBACK_BASE_URL", "http://backend.test/internal/v1")
    monkeypatch.setenv("DISPATCH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AI_ENGINE", "stub")
    get_settings.cache_clear()
    user_id, project_id, environment_id = uuid4(), uuid4(), uuid4()
    context = ProjectContext(str(project_id), SimpleNamespace(user_id=str(user_id)), "owner")
    db.add(Project(id=project_id, owner_id=user_id, name="Example", description="", created_at=analysis.now()))
    db.flush()
    db.add(Environment(id=environment_id, project_id=project_id, name="Staging", kind="staging", base_url="https://example.com",
        revision=1, created_at=analysis.now()))
    db.commit()
    requirement = resources.create_requirement(db, context, RequirementCreate(title="Login", acceptance_criteria=[{"text": "Shows login"}]))
    resources.approve_requirement(db, context, requirement["id"], ApprovalRequest())
    main.app.dependency_overrides[get_db] = lambda: db
    main.app.dependency_overrides[project_access] = lambda: context
    main.app.dependency_overrides[project_manage] = lambda: context
    yield SimpleNamespace(db=db, sessions=sessions, context=context, eid=str(environment_id), rid=requirement["id"], client=TestClient(main.app))
    main.app.dependency_overrides.clear()
    db.close()
    transaction.rollback()
    connection.close()
    engine.dispose()
    get_settings.cache_clear()


def queue(s):
    path = f"/projects/{s.context.project_id}/environments/{s.eid}/runs"
    response = s.client.post(path, json={"requirement_ids": [s.rid]})
    assert response.status_code == 202, response.text
    run = response.json()
    dispatch = s.db.scalar(select(Dispatch).where(Dispatch.run_id == resources.uid(run["id"])))
    envelope = json.loads(analysis.cipher().decrypt(dispatch.encrypted_envelope.encode()))
    return run, dispatch, envelope, path


def send(s, run, envelope, suffix, body, token=None):
    return s.client.post(f'/internal/v1/runs/{run["id"]}/{suffix}', json=body,
        headers={"Authorization": "Bearer " + (token or envelope["callback_token"])})


def event(envelope, sequence, kind, payload):
    return {"event_id": str(uuid4()), "job_id": envelope["job_id"], "attempt": 1, "sequence": sequence,
            "type": kind, "occurred_at": analysis.now().isoformat(), "schema_version": 1, "payload": payload}


def usage(envelope, revision=1, status="reserved", **values):
    return {"event_id": str(uuid4()), "usage_id": "usage-1", "job_id": envelope["job_id"], "attempt": 1,
            "revision": revision, "cost_session_id": "session-1", "provider": "fake", "model": "fake",
            "operation": "test", "tokens": {"reserved_input": 10, "input": None, "output": None},
            "amount": None, "currency": "USD", "status": status,
            "timestamps": {"reserved_at": analysis.now().isoformat(), "finalized_at": analysis.now().isoformat()}, **values}


def test_snapshot_approval_and_project_scoping(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    assert run["run_number"] == 1
    assert envelope["requirements"][0]["criteria"][0]["text"] == "Shows login"
    assert envelope["callback_token"] not in dispatch.encrypted_envelope
    assert "callback_token" not in json.dumps(run)
    resources.update_requirement(s.db, s.context, s.rid, RequirementUpdate(title="Updated"))
    assert envelope["requirements"][0]["title"] == "Login"
    assert s.client.post(path, json={"requirement_ids": [s.rid]}).status_code == 409
    assert s.client.get(f'{path}/{run["id"]}').status_code == 200
    assert s.client.get(path.replace(s.eid, str(uuid4()))).status_code == 404
    assert s.client.post(path, json={"requirement_ids": [s.rid, s.rid]}).status_code == 422
    with pytest.raises(ServiceError) as error:
        resources.delete_requirement(s.db, s.context, s.rid)
    assert error.value.status_code == 409


def test_callback_auth_order_results_and_idempotency(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    running = event(envelope, 1, "job.running", {"status": "running"})
    assert send(s, run, envelope, "execution-events", running, token="wrong").status_code == 401
    assert send(s, run, envelope, "execution-events", running).status_code == 202
    assert send(s, run, envelope, "execution-events", running).status_code == 202
    changed = {**running, "payload": {"status": "running", "changed": True}}
    assert send(s, run, envelope, "execution-events", changed).status_code == 409
    outcome = {"verdict": "inconclusive", "classification": "execution_error", "observed_behavior": "Stub",
               "criterion_verdicts": [{"criterion_id": envelope["requirements"][0]["criteria"][0]["id"], "verdict": "inconclusive",
                   "rationale": "Stub", "source": "engine", "cited_evidence_ids": []}], "actions": []}
    completed = event(envelope, 3, "requirement.completed", {"run_id": run["id"], "requirement_id": s.rid, "outcome": outcome})
    assert send(s, run, envelope, "execution-events", completed).status_code == 202
    finished = event(envelope, 5, "job.finished", {"status": "finished"})
    assert send(s, run, envelope, "execution-events", finished).status_code == 202
    assert send(s, run, envelope, "execution-events", finished).status_code == 202
    assert s.client.get(f'{path}/{run["id"]}/results').json()["items"][0]["criterion_assessments"][0]["criterion_text"] == "Shows login"
    assert s.db.scalar(select(func.count()).select_from(Result)) == 1
    assert s.db.scalar(select(func.count()).select_from(Notification)) == 1
    assert s.client.get(f'{path}/{run["id"]}').json()["status"] == "completed"
    late = event(envelope, 6, "job.running", {"status": "running"})
    assert send(s, run, envelope, "execution-events", late).status_code == 409


def test_usage_revisions_digest_unknown_and_duplicates(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    reserved = usage(envelope)
    assert send(s, run, envelope, "ai-usage", reserved).status_code == 202
    assert send(s, run, envelope, "ai-usage", reserved).status_code == 202
    final = usage(envelope, 2, "succeeded", amount="0.000000000123", tokens={"reserved_input": 10, "input": 3, "output": 2})
    assert send(s, run, envelope, "ai-usage", final).status_code == 202
    assert send(s, run, envelope, "ai-usage", final).status_code == 202
    assert send(s, run, envelope, "ai-usage", {**reserved, "event_id": str(uuid4())}).status_code == 202
    rows = s.db.scalars(select(AIUsage)).all()
    assert len(rows) == 1 and rows[0].amount == Decimal("0.000000000123")
    closure = {"event_id": str(uuid4()), "cost_session_id": "session-1", "revision": 1,
        "final_usage_count": 1, "final_usage_digest": "0" * 64, "closed_at": analysis.now().isoformat()}
    assert send(s, run, envelope, "ai-cost-finalizations", closure).status_code == 503
    closure["final_usage_digest"] = callbacks.usage_digest(rows)
    assert send(s, run, envelope, "ai-cost-finalizations", closure).status_code == 202
    assert send(s, run, envelope, "ai-cost-finalizations", closure).status_code == 202
    cost = s.client.get(f'{path}/{run["id"]}/ai-usage').json()
    assert cost["cost_status"] == "final" and cost["input_tokens"] == 3
    assert cost["estimated_cost_usd"] == 0.000000000123
    assert send(s, run, envelope, "ai-usage", {**final, "usage_id": "new", "event_id": str(uuid4())}).status_code == 409


def test_unknown_is_not_zero_and_empty_closure_is_final_zero(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    unknown = usage(envelope, 2, "unknown")
    assert send(s, run, envelope, "ai-usage", unknown).status_code == 202
    rows = s.db.scalars(select(AIUsage)).all()
    closure = {"event_id": str(uuid4()), "cost_session_id": "session-1", "revision": 1,
        "final_usage_count": 1, "final_usage_digest": callbacks.usage_digest(rows), "closed_at": analysis.now().isoformat()}
    assert send(s, run, envelope, "ai-cost-finalizations", closure).status_code == 202
    cost = s.client.get(f'{path}/{run["id"]}/ai-usage').json()
    assert cost["cost_status"] == "unknown" and cost["estimated_cost_usd"] is None
    second, _, env2, _ = queue(s)
    closure.update(event_id=str(uuid4()), cost_session_id="session-empty", final_usage_count=0, final_usage_digest=callbacks.usage_digest([]))
    assert send(s, second, env2, "ai-cost-finalizations", closure).status_code == 202
    assert s.client.get(f'{path}/{second["id"]}/ai-usage').json()["estimated_cost_usd"] == 0


def test_dispatch_retries_same_envelope_and_cancellation_boundary(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    calls = []
    def handler(request):
        assert request.headers["authorization"] == "Bearer intake-secret"
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(202, json={"job_id": body["job_id"], "run_id": body["run_id"], "duplicate": True})
    assert dispatch_once(s.sessions, httpx.MockTransport(handler))
    s.db.expire_all()
    dispatch = s.db.get(Dispatch, dispatch.id)
    assert dispatch.status == "pending" and dispatch.attempts == 1
    assert s.client.post(f'{path}/{run["id"]}/cancel').status_code == 409
    dispatch.next_attempt_at = analysis.now() - timedelta(seconds=1)
    s.db.commit()
    assert dispatch_once(s.sessions, httpx.MockTransport(handler))
    s.db.expire_all()
    assert s.db.get(Dispatch, dispatch.id).status == "accepted"
    assert calls[0] == calls[1] == envelope
    second, _, _, _ = queue(s)
    assert s.client.post(f'{path}/{second["id"]}/cancel').json()["status"] == "cancelled"


def test_criteria_reconciliation_resets_approval_and_rejects_foreign_ids(setup):
    s = setup
    row = resources.scoped(s.db, Requirement, s.context.project_id, s.rid)
    existing = resources.criteria(s.db, row)[0]
    resources.update_requirement(s.db, s.context, s.rid, RequirementUpdate(acceptance_criteria=[{"id": str(existing.id), "text": "Changed"}, {"text": "New"}]))
    assert row.approval_status == "draft"
    assert len(resources.criteria(s.db, row)) == 2
    with pytest.raises(ServiceError):
        resources.update_requirement(s.db, s.context, s.rid, RequirementUpdate(acceptance_criteria=[{"id": str(uuid4()), "text": "Foreign"}]))


def test_product_submission_idempotency_and_newest_first_pagination(setup):
    s = setup
    path = f"/projects/{s.context.project_id}/environments/{s.eid}/runs"
    data = {"requirement_ids": [s.rid]}
    first = s.client.post(path, json=data, headers={"Idempotency-Key": "click-1"})
    repeated = s.client.post(path, json=data, headers={"Idempotency-Key": "click-1"})
    assert first.status_code == repeated.status_code == 202
    assert first.json()["id"] == repeated.json()["id"]
    changed = s.client.post(path, json={"requirement_ids": [str(uuid4())]}, headers={"Idempotency-Key": "click-1"})
    assert changed.status_code == 409
    second = s.client.post(path, json=data, headers={"Idempotency-Key": "click-2"}).json()
    assert second["run_number"] == 2
    newest = s.client.get(path, params={"limit": 1}).json()
    assert newest["items"][0]["id"] == second["id"]
    older = s.client.get(path, params={"limit": 1, "cursor": newest["next_cursor"]}).json()
    assert older["items"][0]["id"] == first.json()["id"]


def test_dispatch_permanent_failure_is_visible_and_not_retried(setup):
    s = setup
    run, dispatch, envelope, path = queue(s)
    assert dispatch_once(s.sessions, httpx.MockTransport(lambda request: httpx.Response(401)))
    s.db.expire_all()
    assert s.db.get(Dispatch, dispatch.id).status == "failed"
    assert s.client.get(f'{path}/{run["id"]}').json()["status"] == "failed"
    assert not dispatch_once(s.sessions, httpx.MockTransport(lambda request: pytest.fail("Should not retry permanent failures")))


def test_empty_or_partial_outcomes_cannot_finish_a_run(setup):
    s = setup
    run, _, envelope, _ = queue(s)
    finished = event(envelope, 1, "job.finished", {"status": "finished"})
    assert send(s, run, envelope, "execution-events", finished).status_code == 409
    assert s.db.get(AnalysisRun, resources.uid(run["id"])).status == "queued"


def test_sse_replays_durable_usage_after_execution_cursor(setup, monkeypatch):
    from app.services import events
    s = setup
    run, _, envelope, path = queue(s)
    assert send(s, run, envelope, "execution-events", event(envelope, 1, "job.running", {"status": "running"})).status_code == 202
    assert send(s, run, envelope, "ai-usage", usage(envelope)).status_code == 202
    clock = iter([0, 1, 31])
    monkeypatch.setattr(events, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _: None))
    monkeypatch.setattr(events, "SessionLocal", s.sessions)
    response = s.client.get(f'{path}/{run["id"]}/events', headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\nevent: usage" in response.text
    assert "id: 1\n" not in response.text
    assert s.client.get(f'{path}/{run["id"]}/events', headers={"Last-Event-ID": "bad"}).status_code == 422


def test_callbacks_cannot_cross_job_or_run_boundary(setup):
    s = setup
    run, _, envelope, _ = queue(s)
    second, _, env2, _ = queue(s)
    body = usage(envelope)
    assert send(s, second, envelope, "ai-usage", body).status_code == 401
    assert send(s, second, env2, "ai-usage", body).status_code == 409
    assert send(s, run, envelope, "ai-usage", body).status_code == 202
    body.update(job_id=env2["job_id"], event_id=str(uuid4()))
    assert send(s, second, env2, "ai-usage", body).status_code == 409


def test_active_dispatch_lease_is_not_claimed_twice(setup):
    s = setup
    _, dispatch, _, _ = queue(s)
    dispatch.lease_until = analysis.now() + timedelta(seconds=60)
    dispatch.lease_token = "another-worker"
    s.db.commit()
    assert not dispatch_once(s.sessions, httpx.MockTransport(lambda _: pytest.fail("Lease must block delivery")))


@pytest.mark.parametrize("url", ["https://user:secret@example.com", "https://example.com:bad", "https://example.com/ bad", "https:///path"])
def test_target_credentials_are_not_accepted_in_urls(url):
    from pydantic import ValidationError
    from app.schemas.environments import EnvironmentCreate, EnvironmentUpdate
    with pytest.raises(ValidationError):
        EnvironmentCreate(name="Unsafe", base_url=url)
    with pytest.raises(ValidationError):
        EnvironmentUpdate(base_url=url)


def test_environment_revision_invalidates_verification_without_exposing_secrets(setup, monkeypatch):
    from app.schemas.environments import EnvironmentUpdate
    s = setup
    monkeypatch.setenv("ENVIRONMENT_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    environment = resources.scoped(s.db, Environment, s.context.project_id, s.eid)
    environment.verified_at = analysis.now()
    s.db.commit()
    result = resources.update_environment(s.db, s.context, s.eid, EnvironmentUpdate(base_url="https://new.example.com", credentials={"password": "private-password"}))
    assert result["revision"] == 2 and result["verified_at"] is None and result["has_credentials"]
    assert "private-password" not in json.dumps(result, default=str)
    assert "private-password" not in environment.encrypted_credentials


def test_higher_execution_attempt_requires_a_new_product_run(setup):
    s = setup
    run, _, envelope, _ = queue(s)
    body = event(envelope, 1, "job.running", {"status": "running"})
    body["attempt"] = 2
    assert send(s, run, envelope, "execution-events", body).status_code == 409
    metering = usage(envelope)
    metering["attempt"] = 2
    assert send(s, run, envelope, "ai-usage", metering).status_code == 409
