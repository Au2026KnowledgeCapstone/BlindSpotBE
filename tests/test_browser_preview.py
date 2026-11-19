from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.core.errors import ServiceError
from app.services import browser_preview


def setup_preview(monkeypatch, handler, status="accepted"):
    monkeypatch.setattr(browser_preview, "get_run", Mock(return_value=SimpleNamespace(id="run", status="running")))
    monkeypatch.setattr(browser_preview, "get_settings", lambda: SimpleNamespace(ai_service_url="https://ai.test", ai_api_key="test"))
    db = Mock()
    db.scalar.return_value = SimpleNamespace(job_id="job-a", status=status)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ai_transport=httpx.MockTransport(handler))))
    return db, request


async def test_preview_is_bound_to_authorized_run(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/jobs/job-a/browser-preview"
        assert request.headers["Authorization"] == "Bearer test"
        return httpx.Response(200, json={"job_id": "job-a", "status": "running", "frame": None})
    db, request = setup_preview(monkeypatch, handler)
    result = await browser_preview.get_preview(db, "context", "environment", "run", request)
    assert result.frame is None
    browser_preview.get_run.assert_called_once_with(db, "context", "environment", "run")
    db.rollback.assert_called_once()


async def test_wrong_job_frame_is_rejected(monkeypatch):
    db, request = setup_preview(monkeypatch, lambda request: httpx.Response(200, json={"job_id": "other", "status": "running", "frame": None}))
    with pytest.raises(ServiceError) as exc:
        await browser_preview.get_preview(db, None, None, None, request)
    assert exc.value.status_code == 502


async def test_membership_failure_never_contacts_executor(monkeypatch):
    handler = Mock(side_effect=AssertionError("Unauthorized network request"))
    db, request = setup_preview(monkeypatch, handler)
    browser_preview.get_run.side_effect = ServiceError("not_found", "Run not found", 404)
    with pytest.raises(ServiceError):
        await browser_preview.get_preview(db, None, None, None, request)
    handler.assert_not_called()


async def test_pending_dispatch_does_not_contact_executor(monkeypatch):
    handler = Mock(side_effect=AssertionError("Premature network request"))
    db, request = setup_preview(monkeypatch, handler, status="pending")
    result = await browser_preview.get_preview(db, None, None, None, request)
    assert result.frame is None
    handler.assert_not_called()


async def test_oversized_preview_is_rejected(monkeypatch):
    db, request = setup_preview(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 1_500_001))
    with pytest.raises(ServiceError) as exc:
        await browser_preview.get_preview(db, None, None, None, request)
    assert exc.value.status_code == 502
