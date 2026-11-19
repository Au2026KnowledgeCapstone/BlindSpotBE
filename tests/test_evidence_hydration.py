import hashlib
import base64
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from uuid import uuid4

from cryptography.fernet import Fernet

from app.models import Evidence, Result
from app.schemas.capabilities import EvidenceResponse
from app.services import private_storage, capability_client


async def test_existing_remote_screenshot_is_hydrated_locally(tmp_path, monkeypatch):
    eid, rid, pid = uuid4(), uuid4(), uuid4()
    row = Evidence(id=eid, result_id=rid, type="screenshot", storage_key=eid.hex, media_type="image/png")
    result = SimpleNamespace(id=rid, project_id=pid, analysis_run_id=uuid4())
    db = Mock()
    db.get.side_effect = lambda model, identifier: row if model is Evidence else result if model is Result else None
    db.scalar.side_effect = [SimpleNamespace(job_id="executor-job"), result]
    authorize = Mock(return_value=(row, pid))
    monkeypatch.setattr(private_storage, "evidence", authorize)
    monkeypatch.setattr(private_storage, "_resolve", Mock())
    signing_key = Fernet.generate_key().decode()
    monkeypatch.setattr(private_storage, "get_settings", lambda: SimpleNamespace(private_storage_dir=str(tmp_path), download_signing_key=signing_key))
    data = b"\x89PNG\r\n\x1a\nscreenshot"
    fetch = AsyncMock(return_value=EvidenceResponse(id=str(eid), job_id="executor-job", type="screenshot",
        media_type="image/png", content_base64=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest()))
    monkeypatch.setattr(capability_client, "evidence", fetch)
    user = SimpleNamespace(user_id=str(uuid4()))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(auth_settings=SimpleNamespace(backend_origin="http://localhost:8001"))))
    response = await private_storage.get_evidence(db, user, str(eid), request)
    assert response.status_code == 302
    authorize.assert_called_once_with(db, user, str(eid))
    fetch.assert_awaited_once_with(request, "executor-job", str(eid))
    assert private_storage.PrivateStore().available(row.storage_key, row.sha256).read_bytes() == data
    db.add.assert_not_called()  # Hydrates existing metadata rather than duplicating it.
    db.commit.assert_called_once()
    token = response.headers["location"].split("/downloads/", 1)[1]
    image = private_storage.download(db, user, token)
    assert image.headers["Content-Type"] == "image/png"
    assert image.headers["Content-Disposition"].startswith("inline;")
