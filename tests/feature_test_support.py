"""Mock only Supabase's HTTP boundary, never the current-user dependency."""
from contextlib import contextmanager
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend.config import AuthSettings
from backend.main import app

USER_A = {'id':'11111111-1111-4111-8111-111111111111', 'email':'a@example.com'}
USER_B = {'id':'22222222-2222-4222-8222-222222222222', 'email':'b@example.com'}
ORIGIN = 'http://localhost:3000'
CSRF = {'Origin':ORIGIN, 'X-CSRF-Protection':'1', 'Content-Type':'application/json'}


@contextmanager
def feature_client():
    calls, states = [], []
    settings = AuthSettings(supabase_url='https://example.supabase.co',
                            publishable_key='synthetic-key', development=True,
                            frontend_origins=(ORIGIN,), backend_origin='http://localhost:8000')
    def provider(request):
        calls.append(request)
        token = request.headers.get('authorization', '')
        if token == 'Bearer outage':
            return httpx.Response(503, json={})
        user = {'Bearer user-a':USER_A, 'Bearer user-b':USER_B}.get(token)
        return httpx.Response(200, json={**user, 'user_metadata':{'role':'untrusted'}}) if user else httpx.Response(401, json={})

    async def capture(scope, receive, send):
        await app(scope, receive, send)
        if scope['type'] == 'http':
            states.append(scope.get('state', {}).copy())

    with patch.object(app.state, 'auth_settings', settings), \
         patch.object(app.state, 'supabase_transport', httpx.MockTransport(provider), create=True):
        client = TestClient(capture, base_url='http://localhost:8000', follow_redirects=False)
        try:
            yield client, calls, states
        finally:
            client.close()
