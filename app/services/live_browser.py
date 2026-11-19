"""Project-authorized WebSocket bridge to the executor's view-only desktop."""
import asyncio
import time
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import Request, WebSocket
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from app.core.auth import AuthError, AuthenticatedUser, _verify_session
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.deps import _resolve
from app.core.errors import ServiceError
from app.models.integration import Dispatch
from app.services.analysis import get_run


def authorized_job(user, pid, eid, runid):
    with SessionLocal() as db:
        context = _resolve(db, pid, user)
        run = get_run(db, context, eid, runid)
        if run.status not in {"queued", "running"}:
            raise ServiceError("run_finished", "Run is not active.", 409)
        dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == run.id))
        if dispatch is None or dispatch.status != "accepted":
            raise ServiceError("waiting", "Waiting for the executor.", 409)
        return dispatch.job_id


async def serve_live_browser(websocket: WebSocket, pid, eid, runid):
    settings = websocket.app.state.auth_settings
    if websocket.headers.get("origin") not in settings.trusted_origins:
        await websocket.close(code=4403)
        return
    request = Request({**websocket.scope, "type": "http", "method": "GET"})
    try:
        identity = await _verify_session(request)
        user = AuthenticatedUser(user_id=str(identity.id), email=identity.email or "")
        job_id = await asyncio.to_thread(authorized_job, user, pid, eid, runid)
    except (AuthError, ServiceError):
        await websocket.close(code=4403)
        return
    config = get_settings()
    if not config.ai_service_url or not config.ai_api_key:
        await websocket.close(code=4503)
        return
    parsed = urlsplit(config.ai_service_url)
    path = parsed.path.rstrip("/") + "/v1/jobs/" + quote(job_id, safe="") + "/browser-live"
    url = urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc, path, "", ""))
    tasks = []
    try:
        async with connect(url, additional_headers={"Authorization": "Bearer " + config.ai_api_key},
                           subprotocols=["binary"], proxy=None, compression=None, max_size=16_000_000) as desktop:
            await websocket.accept(subprotocol="binary")
            async def upstream():
                while True:
                    message = await websocket.receive_bytes()
                    if len(message) > 1_000_000:
                        return
                    await desktop.send(message)
            async def downstream():
                async for message in desktop:
                    await websocket.send_bytes(message)
            async def membership():
                checked = time.monotonic()
                while True:
                    await asyncio.sleep(5)
                    if await asyncio.to_thread(authorized_job, user, pid, eid, runid) != job_id:
                        return
                    if time.monotonic() - checked > 60:
                        await _verify_session(request)
                        checked = time.monotonic()
            tasks = [asyncio.create_task(f()) for f in (upstream, downstream, membership)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    except (WebSocketDisconnect, ConnectionClosed, InvalidHandshake, OSError, ServiceError, AuthError, asyncio.CancelledError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await websocket.close()
        except (RuntimeError, asyncio.CancelledError):
            pass
