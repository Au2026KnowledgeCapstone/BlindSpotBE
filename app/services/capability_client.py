"""Authenticated, bounded HTTP adapter. Never calls a model or browser in BE."""
import httpx
from pydantic import ValidationError
from app.core.config import get_settings
from app.core.errors import ServiceError


async def call(request, path, body, schema):
    config = get_settings()
    if not config.ai_service_url or not config.ai_service_token:
        raise ServiceError("ai_unavailable", "AI service is not configured.", 503)
    transport = getattr(request.app.state, "ai_transport", None)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.capability_timeout_seconds, connect=10),
                transport=transport, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", config.ai_service_url.rstrip('/') + path,
                    headers={"Authorization": "Bearer " + config.ai_service_token}, json=body) as response:
                if response.status_code in {404, 405, 501}:
                    raise ServiceError("ai_capability_unavailable", "The deployed aiservice does not provide this capability. Deploy the matching capability branch.", 503)
                if response.status_code in {400, 413, 415, 422}:
                    raise ServiceError("ai_document_rejected", "aiservice could not safely read or validate the submitted document set.", response.status_code)
                if response.status_code == 409:
                    raise ServiceError("ai_request_conflict", "AI request ID was reused with different input.", 409)
                if response.status_code != 200:
                    raise ServiceError("ai_unavailable", "AI capability is unavailable or still processing.", 503)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ServiceError("invalid_ai_response", "AI response exceeds the size limit.", 502)
        result = schema.model_validate_json(content)
        if result.request_id != body["request_id"]:
            raise ServiceError("invalid_ai_response", "AI response does not match the request.", 502)
        return result
    except (httpx.HTTPError, ValidationError):
        raise ServiceError("ai_unavailable", "AI capability failed or returned an invalid response.", 503) from None


async def cancel_job(request, job_id):
    """Request cancellation of a job whose dispatch was acknowledged by aiservice."""
    from urllib.parse import quote

    config = get_settings()
    if not config.ai_service_url or not config.ai_service_token:
        raise ServiceError('ai_unavailable', 'AI service is not configured.', 503)
    url = config.ai_service_url.rstrip('/') + '/v1/jobs/' + quote(job_id, safe='') + '/cancel'
    try:
        async with httpx.AsyncClient(timeout=config.dispatch_timeout_seconds,
                transport=getattr(request.app.state, 'ai_transport', None), follow_redirects=False, trust_env=False) as client:
            response = await client.post(url, headers={'Authorization': 'Bearer ' + config.ai_service_token})
        if response.status_code != 200:
            raise ServiceError('ai_unavailable', 'AI service could not confirm cancellation.', 503)
        data = response.json()
        if not isinstance(data, dict) or data.get('job_id') != job_id or data.get('status') not in {'cancelled', 'finished', 'failed'}:
            raise ServiceError('invalid_ai_response', 'AI service returned an invalid cancellation response.', 502)
        return data['status']
    except (httpx.HTTPError, ValueError):
        raise ServiceError('ai_unavailable', 'AI service cancellation failed.', 503) from None
