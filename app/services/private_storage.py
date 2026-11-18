"""Opaque private objects and five-minute, user-bound download grants."""
import json
from urllib.parse import quote
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from app.core.config import get_settings
from app.core.deps import _resolve
from app.core.errors import ServiceError
from app.models import Import, ImportDocument, Evidence, Result, AnalysisRun
from app.services.object_store import store_for, MAX_OBJECT_BYTES
from app.services.resources import uid


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


def content_disposition(filename):
    # RFC 5987: fall back to the percent-encoded form whenever the filename
    # contains anything (e.g. a quote) that would otherwise need escaping out
    # of the quoted-string, rather than interpolating it unescaped.
    encoded = quote(filename)
    if encoded != filename:
        return f"attachment; filename*=utf-8''{encoded}"
    return f'attachment; filename="{filename}"'


def grant(request, kind, row, project_id, user):
    store_for(kind).present(row.storage_key)
    origin = request.app.state.auth_settings.backend_origin
    if not origin:
        raise ServiceError("storage_unavailable", "Backend download origin is not configured.", 503)
    token = signer().encrypt(json.dumps({"kind": kind, "id": str(row.id), "project_id": str(project_id), "user_id": user.user_id}).encode()).decode()
    return RedirectResponse(origin + "/downloads/" + token, status_code=302, headers={"Cache-Control": "no-store"})


def download_document(db, context, iid, did, request):
    row, project_id = document(db, context, iid, did)
    return grant(request, "document", row, project_id, context.user)


async def get_evidence(db, user, eid, request):
    row, project_id = evidence(db, user, eid)
    return grant(request, "evidence", row, project_id, user)


def download(db, user, token):
    try:
        payload = json.loads(signer().decrypt(token.encode(), ttl=300))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise ServiceError("invalid_download", "Download link is invalid or expired.", 403) from None
    if payload.get("user_id") != user.user_id:
        raise ServiceError("invalid_download", "Download link belongs to another user.", 403)
    context = _resolve(db, payload["project_id"], user)
    kind = payload.get("kind")
    if kind == "document":
        row = db.get(ImportDocument, uid(payload["id"]))
        if not row:
            raise ServiceError("not_found", "Source document not found.", 404)
        row, _ = document(db, context, str(row.import_id), str(row.id))
        filename, media = row.filename, "application/octet-stream"
    elif kind == "evidence":
        row, _ = evidence(db, user, payload["id"])
        filename, media = f"evidence-{row.id}", row.media_type or "application/octet-stream"
    else:
        raise ServiceError("invalid_download", "Invalid download kind.", 403)
    data = store_for(kind).read(row.storage_key, row.sha256)
    # Attachments and nosniff keep HTML/text evidence from becoming executable app content.
    return Response(content=data, media_type=media, headers={"Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
        "Content-Disposition": content_disposition(filename)})
