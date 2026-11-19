from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from app.core.errors import ServiceError
from app.services import live_browser


def app_for(monkeypatch):
    app = FastAPI()
    app.state.auth_settings = SimpleNamespace(trusted_origins=('http://localhost:3000',))
    verify = AsyncMock(return_value=SimpleNamespace(id='user', email='test@example.test'))
    monkeypatch.setattr(live_browser, '_verify_session', verify)
    monkeypatch.setattr(live_browser, 'authorized_job', Mock(return_value='job-a'))
    monkeypatch.setattr(live_browser, 'get_settings', lambda: SimpleNamespace(ai_service_url='https://ai.test', ai_api_key='service-secret'))
    @app.websocket('/live')
    async def route(ws: WebSocket):
        await live_browser.serve_live_browser(ws, 'project', 'env', 'run')
    return app, verify


def test_foreign_origin_cannot_open_desktop(monkeypatch):
    app, verify = app_for(monkeypatch)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect('/live', headers={'Origin':'https://evil.test'}, subprotocols=['binary']): pass
    assert error.value.code == 4403
    verify.assert_not_awaited()


def test_other_project_run_cannot_open_desktop(monkeypatch):
    app, _ = app_for(monkeypatch)
    live_browser.authorized_job.side_effect = ServiceError('not_found','Run not found',404)
    upstream = Mock()
    monkeypatch.setattr(live_browser, 'connect', upstream)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/live', headers={'Origin':'http://localhost:3000'}, subprotocols=['binary']): pass
    upstream.assert_not_called()


def test_binary_rfb_stream_is_forwarded_with_server_side_service_auth(monkeypatch):
    import asyncio
    app, _ = app_for(monkeypatch)
    received = []
    sent = asyncio.Event()
    class Desktop:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send(self, value):
            received.append(value)
            sent.set()
        async def __aiter__(self):
            yield b'RFB 003.008\n'
            await sent.wait()
            yield b'framebuffer-update'
    connection = Mock(return_value=Desktop())
    monkeypatch.setattr(live_browser, 'connect', connection)
    with TestClient(app) as client:
        with client.websocket_connect('/live', headers={'Origin':'http://localhost:3000'}, subprotocols=['binary']) as stream:
            assert stream.accepted_subprotocol == 'binary'
            assert stream.receive_bytes() == b'RFB 003.008\n'
            stream.send_bytes(b'RFB 003.008\n')
            assert stream.receive_bytes() == b'framebuffer-update'
            with pytest.raises(WebSocketDisconnect):
                stream.receive_bytes()
    args, kwargs = connection.call_args
    assert args[0] == 'wss://ai.test/v1/jobs/job-a/browser-live'
    assert kwargs['additional_headers'] == {'Authorization':'Bearer service-secret'}
    assert kwargs['subprotocols'] == ['binary']
    assert received == [b'RFB 003.008\n']
