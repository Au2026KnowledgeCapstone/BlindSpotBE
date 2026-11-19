from types import SimpleNamespace
from unittest.mock import Mock
import httpx
import pytest

from app.core.errors import ServiceError
from app.services import run_timeline


def setup(monkeypatch, handler):
    monkeypatch.setattr(run_timeline, "get_run", Mock(return_value=SimpleNamespace(id="run")))
    monkeypatch.setattr(run_timeline, "get_settings", lambda: SimpleNamespace(ai_service_url="https://ai.test", ai_api_key="secret"))
    db = Mock()
    db.scalar.return_value = SimpleNamespace(job_id="job", status="accepted")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ai_transport=httpx.MockTransport(handler))))
    return db, request


async def test_timeline_is_authorized_and_cursor_is_forwarded(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/jobs/job/timeline"
        assert request.url.params["after"] == "4"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={"job_id": "job", "events": [], "next_cursor": 4})
    db, request = setup(monkeypatch, handler)
    result = await run_timeline.timeline(db, "context", "env", "run", 4, request)
    run_timeline.get_run.assert_called_once_with(db, "context", "env", "run")
    assert result.next_cursor == 4
    db.rollback.assert_called_once()


async def test_unauthorized_run_never_contacts_executor(monkeypatch):
    handler = Mock()
    db, request = setup(monkeypatch, handler)
    run_timeline.get_run.side_effect = ServiceError("not_found", "Run not found", 404)
    with pytest.raises(ServiceError):
        await run_timeline.timeline(db, None, None, None, 0, request)
    handler.assert_not_called()


@pytest.mark.parametrize("job,cursor", [("another-job", 4), ("job", 3)])
async def test_wrong_job_or_backwards_cursor_is_rejected(monkeypatch, job, cursor):
    db, request = setup(monkeypatch, lambda request: httpx.Response(200, json={"job_id": job, "events": [], "next_cursor": cursor}))
    with pytest.raises(ServiceError) as error:
        await run_timeline.timeline(db, None, None, None, 4, request)
    assert error.value.status_code == 502
