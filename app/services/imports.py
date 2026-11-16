"""Retain originals, delegate extraction, persist draft requirements atomically."""
import base64
import hashlib
import json
from pathlib import PurePath
from uuid import uuid4
from sqlalchemy import select
from app.core.errors import ServiceError
from app.models import Import, ImportDocument, Requirement, AcceptanceCriterion
from app.models.assets import ImportRequirement
from app.schemas.capabilities import ExtractionResponse
from app.services import capability_client
from app.services.resources import uid, scoped, requirement_out
from app.services.private_storage import PrivateStore, signer, MAX_OBJECT_BYTES

ALLOWED = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def get_import(db, context, iid):
    row = scoped(db, Import, context.project_id, iid)
    if row.status != "completed":
        raise ServiceError("import_pending", "This import has not completed; retry the same upload with its Idempotency-Key.", 409)
    documents = db.scalars(select(ImportDocument).where(ImportDocument.import_id == row.id).order_by(ImportDocument.role)).all()
    requirements = db.scalars(select(Requirement).join(ImportRequirement, ImportRequirement.requirement_id == Requirement.id).where(
        ImportRequirement.import_id == row.id).order_by(Requirement.id)).all()
    return {"import_id": str(row.id), "documents": [{"id": str(d.id), "role": d.role, "filename": d.filename, "sha256": d.sha256} for d in documents],
            "requirements": [requirement_out(db, r) for r in requirements], "warnings": row.warnings}


async def create_import(db, context, request, brd, srs, design_spec=None):
    # Validate configured storage/signing before asking a model to do paid work.
    store = PrivateStore()
    signer()
    files = []
    total = 0
    for role, upload in (("brd", brd), ("srs", srs), ("design_spec", design_spec)):
        if upload is None:
            continue
        name = upload.filename or ""
        if not name or len(name) > 200 or any(c in name for c in "/\\\x00\r\n") or PurePath(name).suffix.lower() not in ALLOWED:
            raise ServiceError("invalid_document", "Upload a simple TXT, Markdown, PDF or DOCX filename.", 415)
        content = await upload.read(MAX_OBJECT_BYTES + 1)
        total += len(content)
        if not content or total > MAX_OBJECT_BYTES:
            raise ServiceError("invalid_document", "The complete document set must contain 1 byte to 10 MiB.", 413)
        files.append({"id": str(uuid4()), "role": role, "filename": name, "content_type": upload.content_type or "application/octet-stream",
                      "content": content, "sha256": hashlib.sha256(content).hexdigest()})
    digest = hashlib.sha256(json.dumps([(f["role"], f["filename"], f["content_type"], f["sha256"]) for f in files]).encode()).hexdigest()
    key = request.headers.get("idempotency-key")
    if key is not None and (not key.strip() or len(key) > 128):
        raise ServiceError("validation_error", "Idempotency-Key must contain 1 to 128 nonblank characters.", 422)
    scoped_key = hashlib.sha256(json.dumps([context.project_id, context.user.user_id, key]).encode()).hexdigest() if key else None
    # Serialize admission only; no transaction is held during the external call.
    from app.models import Project
    db.scalar(select(Project).where(Project.id == uid(context.project_id)).with_for_update())
    row = db.scalar(select(Import).where(Import.request_key == scoped_key)) if scoped_key else None
    if row:
        if row.fingerprint != digest:
            raise ServiceError("conflict", "Idempotency-Key was reused with different documents.", 409)
        if row.status == "completed":
            return get_import(db, context, str(row.id))
        saved = db.scalars(select(ImportDocument).where(ImportDocument.import_id == row.id)).all()
        for file in files:
            file["id"] = str(next(d.id for d in saved if d.role == file["role"]))
    else:
        row = Import(id=uuid4(), project_id=uid(context.project_id), created_by=uid(context.user.user_id),
                     request_key=scoped_key, fingerprint=digest, status="pending", warnings=[])
        stored = []
        try:
            db.add(row)
            db.flush()
            for file in files:
                storage_key = store.put(file["content"])
                stored.append(storage_key)
                db.add(ImportDocument(id=uid(file["id"]), import_id=row.id, role=file["role"], filename=file["filename"],
                                      storage_key=storage_key, sha256=file["sha256"]))
            db.commit()
        except Exception:
            db.rollback()
            for storage_key in stored:
                store.remove(storage_key)
            raise
    import_id = row.id
    payload = {"request_id": str(import_id), "documents": [{k: f[k] for k in ("id", "role", "filename", "content_type")} |
        {"content_base64": base64.b64encode(f["content"]).decode()} for f in files]}
    db.rollback()
    result = await capability_client.call(request, "/v1/imports", payload, ExtractionResponse)
    # Membership may have changed while extraction was running.
    from app.core.deps import _resolve
    _resolve(db, context.project_id, context.user)
    row = scoped(db, Import, context.project_id, import_id, lock=True)
    if row.status == "completed":
        return get_import(db, context, str(import_id))
    originals = {f["id"]: f for f in files}
    for value in result.requirements:
        source = originals.get(value.document_id)
        if source is None or value.char_end <= value.char_start:
            raise ServiceError("invalid_ai_response", "Extraction citation does not match an uploaded document.", 502)
        requirement = Requirement(id=uuid4(), project_id=row.project_id, title=value.title, description=value.description,
            category=value.category, priority=value.priority, approval_status="needs_clarification" if value.clarification_reason else "draft",
            source={"kind": "imported", "document_name": source["filename"], "document_role": source["role"], "excerpt": value.excerpt,
                    "char_start": value.char_start, "char_end": value.char_end, "warnings": [value.clarification_reason] if value.clarification_reason else []})
        db.add(requirement)
        db.flush()
        for position, text in enumerate(value.criteria):
            if not text.strip():
                raise ServiceError("invalid_ai_response", "Extracted criteria cannot be blank.", 502)
            db.add(AcceptanceCriterion(id=uuid4(), project_id=row.project_id, requirement_id=requirement.id, text=text, position=position))
        db.add(ImportRequirement(import_id=row.id, requirement_id=requirement.id))
    row.status, row.warnings = "completed", result.warnings
    db.commit()
    return get_import(db, context, str(import_id))
