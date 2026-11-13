"""Run with python -m app.services.dispatch. Leased, retryable HTTP outbox."""
import argparse
import json
import time
from datetime import timedelta
from uuid import uuid4
import httpx
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.integration import Dispatch
from app.models import AnalysisRun, Notification
from app.services.analysis import now, cipher


def dispatch_once(sessions=SessionLocal, transport=None):
    settings = get_settings()
    with sessions.begin() as db:
        row = db.scalar(select(Dispatch).where(Dispatch.status == "pending", Dispatch.next_attempt_at <= now(),
            (Dispatch.lease_until.is_(None)) | (Dispatch.lease_until <= now())).order_by(Dispatch.created_at).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        row.attempts += 1
        row.lease_token = token = str(uuid4())
        row.lease_until = now() + timedelta(seconds=settings.dispatch_lease_seconds)
        identifier, encrypted, run_id = row.id, row.encrypted_envelope, row.run_id
    status, error = "pending", None
    try:
        envelope = json.loads(cipher().decrypt(encrypted.encode()))
        with httpx.Client(timeout=settings.dispatch_timeout_seconds, transport=transport, follow_redirects=False, trust_env=False) as client:
            response = client.post(settings.ai_service_url.rstrip('/') + '/v1/jobs', json=envelope,
                                   headers={"Authorization": f"Bearer {settings.ai_api_key}"})
        if response.status_code == 202:
            accepted = response.json()
            if accepted.get("job_id") == envelope["job_id"] and accepted.get("run_id") == envelope["run_id"]:
                status = "accepted"
            else:
                error = "invalid_acknowledgment"
        elif response.status_code in {408, 429} or response.status_code >= 500:
            error = "retryable_http"
        else:
            status, error = "failed", "permanent_http"
    except Exception as exc:
        error = type(exc).__name__  # Never persist response bodies, tokens or envelopes.
    with sessions.begin() as db:
        run = db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update())
        row = db.scalar(select(Dispatch).where(Dispatch.id == identifier).with_for_update())
        if row.lease_token == token:
            row.status, row.last_error = status, error
            row.lease_until = row.lease_token = None
            row.next_attempt_at = now() + timedelta(seconds=min(300, 2 ** min(row.attempts, 9)))
            if status == "failed" and run.status == "queued":
                run.status, run.completed_at, run.error = "failed", now(), "AI service rejected job dispatch."
                db.add(Notification(id=uuid4(), user_id=run.requested_by, project_id=run.project_id,
                    message=f"Run #{run.run_number} failed during dispatch.", created_at=now()))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    options = parser.parse_args()
    while True:
        worked = dispatch_once()
        if options.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
