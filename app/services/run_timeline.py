from urllib.parse import quote
import httpx
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ServiceError
from app.models.integration import Dispatch
from app.schemas.run_timeline import RunTimeline
from app.services.analysis import get_run


async def timeline(db, context, eid, runid, after, request):
    run = get_run(db, context, eid, runid)
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == run.id))
    if dispatch is None:
        raise ServiceError("not_found", "Run dispatch not found.", 404)
    job = dispatch.job_id
    if dispatch.status != "accepted":
        return RunTimeline(job_id=job, events=[], next_cursor=after)
    db.rollback()
    settings = get_settings()
    if not settings.ai_service_url or not settings.ai_api_key:
        raise ServiceError("timeline_unavailable", "Execution timeline is not configured.", 503)
    url = settings.ai_service_url.rstrip('/') + '/v1/jobs/' + quote(job, safe='') + '/timeline'
    try:
        async with httpx.AsyncClient(timeout=10, transport=getattr(request.app.state, 'ai_transport', None), follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', url, params={'after': after}, headers={'Authorization': 'Bearer ' + settings.ai_api_key}) as response:
                if response.status_code != 200:
                    raise ServiceError("timeline_unavailable", "Execution timeline is temporarily unavailable.", 503)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ServiceError("invalid_ai_response", "Execution timeline exceeds the limit.", 502)
        result = RunTimeline.model_validate_json(content)
        if result.job_id != job or result.next_cursor < after:
            raise ServiceError("invalid_ai_response", "Execution timeline does not match this run.", 502)
        return result
    except (httpx.HTTPError, ValidationError):
        raise ServiceError("timeline_unavailable", "Execution timeline is temporarily unavailable.", 503) from None
