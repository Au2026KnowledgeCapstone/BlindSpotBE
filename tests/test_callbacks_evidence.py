"""record_evidence() in isolation -- no Postgres required.

The end-to-end path (a real requirement.completed callback persisting Evidence
rows) is covered by tests/test_owned_endpoints.py, which needs the disposable
Postgres fixture. This file exercises just the dedup/idempotency logic with a
fake session, so it runs anywhere.
"""
from uuid import uuid4

from app.models import Evidence
from app.services.callbacks import Outcome, record_evidence
from app.services.resources import uid


class FakeSession:
    def __init__(self):
        self.store: dict[str, Evidence] = {}
        self.added: list[Evidence] = []

    def get(self, model, key):
        return self.store.get(str(key))

    def add(self, obj):
        self.added.append(obj)
        self.store[str(obj.id)] = obj


class FakeResult:
    def __init__(self):
        self.id = uuid4()


def _outcome(**overrides):
    base = {"verdict": "pass", "classification": "criteria_satisfied", "observed_behavior": "ok",
            "criterion_verdicts": [], "actions": []}
    base.update(overrides)
    return Outcome.model_validate(base)


def test_record_evidence_inserts_screenshot_rows_from_actions_and_criteria():
    db, result = FakeSession(), FakeResult()
    from_action, from_criterion = uuid4().hex, uuid4().hex
    outcome = _outcome(
        actions=[{"index": 0, "kind": "click", "description": "x", "outcome": "completed", "evidence_id": from_action}],
        criterion_verdicts=[{"criterion_id": str(uuid4()), "verdict": "pass", "rationale": "r",
                              "cited_evidence_ids": [from_criterion], "source": "engine"}],
    )
    record_evidence(db, result, outcome)
    assert {str(row.id) for row in db.added} == {str(uid(from_action)), str(uid(from_criterion))}
    for row in db.added:
        assert row.type == "screenshot"
        assert row.media_type == "image/png"
        assert row.result_id == result.id
        assert row.storage_key in (from_action, from_criterion)  # exact sink-issued string, not reformatted


def test_record_evidence_dedupes_within_a_result_and_skips_rows_that_already_exist():
    db, result = FakeSession(), FakeResult()
    shared = uuid4().hex
    outcome = _outcome(
        actions=[{"index": 0, "kind": "click", "description": "x", "outcome": "completed", "evidence_id": shared}],
        criterion_verdicts=[{"criterion_id": str(uuid4()), "verdict": "pass", "rationale": "r",
                              "cited_evidence_ids": [shared], "source": "engine"}],
    )
    record_evidence(db, result, outcome)
    assert len(db.added) == 1  # cited by both an action and a criterion in the same result

    other_result = FakeResult()
    record_evidence(db, other_result, outcome)
    assert len(db.added) == 1  # already recorded (e.g. shared with an earlier result); not duplicated


def test_record_evidence_ignores_actions_with_no_evidence():
    db, result = FakeSession(), FakeResult()
    outcome = _outcome(actions=[{"index": 0, "kind": "click", "description": "x", "outcome": "stopped", "evidence_id": None}])
    record_evidence(db, result, outcome)
    assert db.added == []
