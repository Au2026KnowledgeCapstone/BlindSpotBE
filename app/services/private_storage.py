"""Opaque private objects and five-minute, user-bound download grants."""
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet, InvalidToken
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from app.core.config import get_settings
from app.core.deps import _resolve
from app.core.errors import ServiceError
from app.models import Import, ImportDocument, Evidence, Result, AnalysisRun
from app.models.integration import Dispatch, ResultDetail
from app.services.resources import uid

MAX_OBJECT_BYTES = 10 * 1024 * 1024


class PrivateStore:
    def __init__(self):
        directory = get_settings().private_storage_dir
        if not directory:
            raise ServiceError("storage_unavailable", "Private storage is not configured.", 503)
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        return path

    def put(self, data):
        if not data or len(data) > MAX_OBJECT_BYTES:
            raise ServiceError("invalid_upload", "Objects must contain 1 byte to 10 MiB.", 413)
        key = uuid4().hex
        with self.path(key).open("xb") as output:
            os.chmod(output.name, 0o600)
            output.write(data)
        return key

    def remove(self, key):
        self.path(key).unlink(missing_ok=True)

    def available(self, key, expected_sha=None):
        path = self.path(key)
        if not path.is_file() or path.stat().st_size > MAX_OBJECT_BYTES:
            raise ServiceError("not_found", "Private object is unavailable.", 404)
        if expected_sha and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise ServiceError("artifact_corrupt", "Private object integrity check failed.", 409)
        return path


def signer():
    key = get_settings().download_signing_key
    if not key:
        raise ServiceError("storage_unavailable", "Download signing is not configured.", 503)
    return Fernet(key.encode())


def document(db, context, iid, did):
    imported = db.scalar(select(Import).where(Import.id == uid(iid), Import.project_id == uid(context.project_id)))
    row = db.scalar(select(ImportDocument).where(ImportDocument.id == uid(did), ImportDocument.import_id == uid(iid))) if imported else None
    if not row:
        raise ServiceError("not_found", "Source document not found.", 404)
    return row, imported.project_id


def evidence(db, user, eid):
    result = db.execute(select(Evidence, Result.project_id).join(Result, Evidence.result_id == Result.id).where(Evidence.id == uid(eid))).first()
    if not result:
        raise ServiceError("not_found", "Evidence not found.", 404)
    _resolve(db, str(result[1]), user)
    return result


def grant(request, kind, row, project_id, user):
    PrivateStore().available(row.storage_key, row.sha256)
    origin = request.app.state.auth_settings.backend_origin
    if not origin:
        raise ServiceError("storage_unavailable", "Backend download origin is not configured.", 503)
    token = signer().encrypt(json.dumps({"kind": kind, "id": str(row.id), "project_id": str(project_id), "user_id": user.user_id}).encode()).decode()
    return RedirectResponse(origin + "/downloads/" + token, status_code=302, headers={"Cache-Control": "no-store"})


def download_document(db, context, iid, did, request):
    row, project_id = document(db, context, iid, did)
    return grant(request, "document", row, project_id, context.user)


async def get_evidence(db, user, eid, request):
    row = db.get(Evidence, uid(eid))
    if row:
        row, project_id = evidence(db, user, eid)
        return grant(request, "evidence", row, project_id, user)
    # A1 references point into the executor outbox. Resolve only references
    # actually cited by a persisted result before contacting the executor.
    from sqlalchemy import Text
    candidates = db.execute(select(ResultDetail, Result).join(Result, Result.id == ResultDetail.result_id).where(
        ResultDetail.outcome.cast(Text).contains(str(uid(eid)), autoescape=True))).all()
    result = None
    for detail, candidate in candidates:
        references = [a.get("evidence_id") for a in detail.outcome.get("actions", [])]
        references += [value for c in detail.outcome.get("criterion_verdicts", []) for value in c.get("cited_evidence_ids", [])]
        if str(uid(eid)) in references:
            result = candidate
            break
    if result is None:
        raise ServiceError("not_found", "Evidence not found.", 404)
    _resolve(db, str(result.project_id), user)
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == result.analysis_run_id))
    if dispatch is None:
        raise ServiceError("not_found", "Evidence job is unavailable.", 404)
    project_id, result_id, job_id = result.project_id, result.id, dispatch.job_id
    db.rollback()
    from app.services import capability_client
    payload = await capability_client.evidence(request, job_id, str(uid(eid)))
    import base64
    from datetime import datetime
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
        captured_at = datetime.fromisoformat(payload.captured_at) if payload.captured_at else None
    except (ValueError, TypeError):
        raise ServiceError("invalid_ai_response", "Evidence data is invalid.", 502) from None
    if hashlib.sha256(data).hexdigest() != payload.sha256:
        raise ServiceError("artifact_corrupt", "Evidence integrity check failed.", 502)
    _resolve(db, str(project_id), user)
    # Serialize cache insertion so concurrent downloads do not create duplicate objects.
    db.scalar(select(Result).where(Result.id == result_id).with_for_update())
    row = db.get(Evidence, uid(eid))
    if row is None:
        store = PrivateStore()
        key = store.put(data)
        try:
            row = Evidence(id=uid(eid), result_id=result_id, type=payload.type, storage_key=key,
                media_type=payload.media_type, sha256=payload.sha256, captured_at=captured_at)
            db.add(row)
            db.commit()
        except Exception:
            db.rollback()
            store.remove(key)
            raise
    return grant(request, "evidence", row, project_id, user)


def download(db, user, token):
    try:
        payload = json.loads(signer().decrypt(token.encode(), ttl=300))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise ServiceError("invalid_download", "Download link is invalid or expired.", 403) from None
    if payload.get("user_id") != user.user_id:
        raise ServiceError("invalid_download", "Download link belongs to another user.", 403)
    context = _resolve(db, payload["project_id"], user)
    if payload.get("kind") == "document":
        row = db.get(ImportDocument, uid(payload["id"]))
        if not row:
            raise ServiceError("not_found", "Source document not found.", 404)
        row, _ = document(db, context, str(row.import_id), str(row.id))
        filename, media = row.filename, "application/octet-stream"
    elif payload.get("kind") == "evidence":
        row, _ = evidence(db, user, payload["id"])
        filename, media = f"evidence-{row.id}", row.media_type or "application/octet-stream"
    else:
        raise ServiceError("invalid_download", "Invalid download kind.", 403)
    path = PrivateStore().available(row.storage_key, row.sha256)
    # Attachments and nosniff keep HTML/text evidence from becoming executable app content.
    return FileResponse(path, media_type=media, filename=filename,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})
