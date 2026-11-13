"""Replayable run SSE from the durable callback inbox."""
import json
import time
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.core.db import SessionLocal
from app.core.deps import _resolve
from app.core.errors import ServiceError
from app.models.integration import Callback
from app.services.analysis import get_run


def stream(db, context, eid, runid, request):
    run = get_run(db, context, eid, runid)
    raw = request.headers.get("last-event-id") or request.query_params.get("after", "0")
    try:
        after = int(raw)
        if after < 0:
            raise ValueError()
    except ValueError:
        raise ServiceError("validation_error", "Event cursor must be a nonnegative integer.", 422) from None
    run_id = run.id
    db.rollback()  # No transaction stays open across the stream.

    def generate():
        cursor = after
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                try:
                    _resolve(session, context.project_id, context.user)
                except ServiceError:
                    return
                rows = session.scalars(select(Callback).where(Callback.run_id == run_id, Callback.position > cursor)
                    .order_by(Callback.position).limit(100)).all()
                messages = [(row.position, row.kind, row.payload) for row in rows]
            for position, kind, payload in messages:
                cursor = position
                yield f"id: {position}\nevent: {kind}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
            if not messages:
                yield ": keep-alive\n\n"
                time.sleep(1)
        # Reconnect resumes at the last durable ID; no events are lost at timeout.
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})
