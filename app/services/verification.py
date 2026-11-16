"""Verify a frozen environment revision without overwriting later edits."""
import json
from uuid import uuid4
from app.models import Environment
from app.models.assets import EnvironmentVerification
from app.schemas.capabilities import VerificationResponse
from app.services import capability_client
from app.services.analysis import now
from app.services.resources import scoped, credential_cipher
from app.core.errors import ServiceError
from app.core.deps import _resolve


async def verify(db, context, eid, request):
    environment = scoped(db, Environment, context.project_id, eid, lock=True)
    credentials = {}
    if environment.encrypted_credentials:
        try:
            credentials = json.loads(credential_cipher().decrypt(environment.encrypted_credentials.encode()))
        except ServiceError:
            raise
        except Exception:
            raise ServiceError("credentials_unavailable", "Credentials could not be decrypted.", 503) from None
    verification = EnvironmentVerification(id=uuid4(), project_id=environment.project_id, environment_id=environment.id,
        revision=environment.revision, status="pending")
    db.add(verification)
    db.commit()
    identifier, revision, environment_id = verification.id, verification.revision, str(environment.id)
    payload = {"request_id": str(identifier), "environment_id": environment_id, "revision": revision,
               "target_url": environment.base_url, "credentials": credentials}
    db.rollback()
    try:
        response = await capability_client.call(request, "/v1/environments/verify", payload, VerificationResponse)
    except ServiceError:
        verification = db.get(EnvironmentVerification, identifier)
        if verification:
            verification.status, verification.detail = "unavailable", "Verification service failed."
            db.commit()
        raise
    if response.environment_id != environment_id or response.revision != revision:
        raise ServiceError("invalid_ai_response", "Verification result does not match its environment revision.", 502)
    _resolve(db, context.project_id, context.user)
    environment = scoped(db, Environment, context.project_id, eid, lock=True)
    verification = db.get(EnvironmentVerification, identifier)
    if environment.revision != revision:
        verification.status = "stale"
    else:
        verification.status = response.status
        environment.verified_at = now() if response.status == "verified" else None
    verification.detail = response.reason
    db.commit()
    return {"status": verification.status}
