"""Authorize the run before reading its executor's latest browser frame."""
from urllib.parse import quote

import httpx
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import ServiceError
from app.models.integration import Dispatch
from app.schemas.browser_preview import BrowserPreview
from app.services.analysis import get_run


async def get_preview(db, context, eid, runid, request):
    run = get_run(db, context, eid, runid)
    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == run.id))
    if dispatch is None:
        raise ServiceError("not_found", "Run dispatch not found.", 404)
    job_id = dispatch.job_id
    if dispatch.status != "accepted":
        return BrowserPreview(job_id=job_id, status=run.status)
    db.rollback()
    config = get_settings()
    if not config.ai_service_url or not config.ai_api_key:
        raise ServiceError("ai_unavailable", "Browser preview is not configured.", 503)
    url = config.ai_service_url.rstrip('/') + '/v1/jobs/' + quote(job_id, safe='') + '/browser-preview'
    try:
        async with httpx.AsyncClient(timeout=10, transport=getattr(request.app.state, 'ai_transport', None),
                                     follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', url, headers={'Authorization': 'Bearer ' + config.ai_api_key}) as response:
                if response.status_code != 200:
                    raise ServiceError("preview_unavailable", "Browser preview is temporarily unavailable.", 503)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 1_500_000:
                        raise ServiceError("invalid_ai_response", "Browser preview exceeds the size limit.", 502)
        preview = BrowserPreview.model_validate_json(content)
        if preview.job_id != job_id:
            raise ServiceError("invalid_ai_response", "Browser preview does not match this run.", 502)
        return preview
    except (httpx.HTTPError, ValidationError):
        raise ServiceError("preview_unavailable", "Browser preview is temporarily unavailable.", 503) from None
