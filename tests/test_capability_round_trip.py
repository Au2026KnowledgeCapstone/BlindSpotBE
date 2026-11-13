"""Real BE → aiservice HTTP capabilities; fake model, real local Chromium."""
import json
import os
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import pytest
from app.core.config import get_settings
from app.schemas.environments import EnvironmentUpdate
from app.services import resources
from test_owned_endpoints import owned, files
from test_integration import setup
from test_executor_round_trip import port, wait_for


@pytest.mark.skipif(os.getenv('RUN_BROWSER_CAPABILITY_TEST') != '1', reason='Opt-in cross-service browser test')
def test_import_download_and_real_browser_verification(owned, monkeypatch, tmp_path):
    root = os.environ.get('AISERVICE_REPO')
    if not root:
        pytest.skip('Set AISERVICE_REPO to the capability branch')
    source = Path(root).resolve()
    python = os.environ.get('AISERVICE_PYTHON', str(source / '.venv/bin/python'))
    ai_port = port()
    # Fake provider injection exists only in this temporary test application.
    harness = tmp_path / 'capabilities_harness.py'
    harness.write_text('''
import json, httpx
from app.main import create_app
from app.capabilities.service import Capabilities
from app.capabilities.extraction import Extractor
def provider(request):
    body = json.loads(request.content)
    passage = json.loads(body['messages'][1]['content'])['passages'][0]
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
        'requirements': [{'title': 'Login', 'description': 'Documented login', 'criteria': ['Users can sign in.'], 'passage_id': passage['id']}]})}}],
        'usage': {'prompt_tokens': 12, 'completion_tokens': 5}})
app = create_app(capabilities_factory=lambda c, s: Capabilities(c, s, extractor=Extractor(c, httpx.MockTransport(provider))))
''')
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{tmp_path / "aiservice.db"}', 'SERVICE_TOKEN': 'intake-secret',
        'ENGINE': 'stub', 'EXTRACTION_API_KEY': 'test-only', 'EXTRACTION_MODEL': 'test-only',
        'VERIFICATION_ENABLED': 'true', 'VERIFICATION_ALLOWED_PRIVATE_HOSTS': '127.0.0.1',
        'VERIFICATION_TIMEOUT_SECONDS': '8', 'PYTHONPATH': str(source)}
    subprocess.run([python, '-m', 'alembic', 'upgrade', 'head'], cwd=source, env=environment, check=True, capture_output=True)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''<form onsubmit="event.preventDefault(); if(document.querySelector('[type=password]').value==='correct') document.querySelector('#welcome').hidden=false">
                <input type="email"><input type="password"><button type="submit">Login</button></form><div id="welcome" hidden>Welcome</div>''')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with (tmp_path / 'capabilities.log').open('w') as log:
        process = subprocess.Popen([python, '-m', 'uvicorn', '--app-dir', str(tmp_path), 'capabilities_harness:app',
            '--host', '127.0.0.1', '--port', str(ai_port)], cwd=source, env=environment, stdout=log, stderr=log)
        try:
            wait_for(f'http://127.0.0.1:{ai_port}/health', process)
            monkeypatch.setenv('AI_SERVICE_URL', f'http://127.0.0.1:{ai_port}')
            get_settings.cache_clear()
            s = owned
            path = f'/projects/{s.context.project_id}/imports'
            response = s.client.post(path, files=files(), headers={'Idempotency-Key': 'real-import'})
            assert response.status_code == 201, response.text
            imported = response.json()
            assert imported['requirements'][0]['approval_status'] == 'draft'
            assert imported['requirements'][0]['source']['excerpt'] == 'Users shall sign in.'
            document = imported['documents'][0]
            response = s.client.get(f'{path}/{imported["import_id"]}/documents/{document["id"]}', follow_redirects=False)
            assert response.status_code == 302
            assert s.client.get(urlsplit(response.headers['location']).path).content in [f[1] for f in files().values()]
            resources.update_environment(s.db, s.context, s.eid, EnvironmentUpdate(
                base_url=f'http://127.0.0.1:{server.server_port}', credentials={'email': 'demo@example.test',
                'password': 'correct', 'success_selector': '#welcome'}))
            response = s.client.post(f'/projects/{s.context.project_id}/environments/{s.eid}/verify')
            assert response.status_code == 202 and response.json()['status'] == 'verified', response.text
        finally:
            process.terminate()
            process.wait(timeout=10)
            server.shutdown()
            thread.join()
            server.server_close()
