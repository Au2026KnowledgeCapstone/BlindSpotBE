"""Previously unfinished assigned endpoints, exercised with PostgreSQL."""
import base64
import hashlib
import json
import time
from urllib.parse import urlsplit
from uuid import uuid4
from dataclasses import replace
import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, func
import main
from app.core.auth import current_user
from app.core.auth_config import AuthSettings
from app.core.config import get_settings
from app.core.deps import project_access, project_manage
from app.models import Import, ImportDocument, Requirement, Evidence, Environment
from app.services.private_storage import PrivateStore, signer
from test_integration import setup, queue, send, event


@pytest.fixture
def owned(setup, monkeypatch, tmp_path):
    s = setup
    monkeypatch.setenv('PRIVATE_STORAGE_DIR', str(tmp_path / 'private'))
    monkeypatch.setenv('DOWNLOAD_SIGNING_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('ENVIRONMENT_CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    get_settings.cache_clear()
    original_settings = getattr(main.app.state, 'auth_settings', None)
    main.app.state.auth_settings = AuthSettings(development=True,
        frontend_origins=('http://localhost:3000',), backend_origin='http://localhost:8000')
    main.app.dependency_overrides[current_user] = lambda: s.context.user
    yield s
    main.app.state.auth_settings = original_settings


def files():
    return {'brd': ('brd.txt', b'Users shall sign in.', 'text/plain'),
            'srs': ('srs.txt', b'Users shall see the dashboard after login.', 'text/plain')}


def extracted(request):
    body = json.loads(request.content)
    document = body['documents'][0]
    text = base64.b64decode(document['content_base64']).decode()
    return httpx.Response(200, json={'request_id': body['request_id'], 'requirements': [{
        'title': 'Login', 'description': 'Allow login', 'criteria': ['Users can sign in.'],
        'document_id': document['id'], 'excerpt': text, 'char_start': 0, 'char_end': len(text)}], 'warnings': []})


def install_transport(monkeypatch, handler):
    monkeypatch.setattr(main.app.state, 'ai_transport', httpx.MockTransport(handler), raising=False)


def test_import_retention_readback_and_submission_replay(owned, monkeypatch):
    s = owned
    calls = []
    def ai(request):
        assert request.url.path == '/v1/imports'
        assert request.headers['authorization'] == 'Bearer intake-secret'
        calls.append(request)
        return extracted(request)
    install_transport(monkeypatch, ai)
    path = f'/projects/{s.context.project_id}/imports'
    response = s.client.post(path, files=files(), headers={'Idempotency-Key': 'upload-1'})
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body['documents']) == 2 and body['requirements'][0]['approval_status'] == 'draft'
    assert body['requirements'][0]['source']['excerpt'] == 'Users shall sign in.'
    assert s.client.get(path + '/' + body['import_id']).json() == body
    replay = s.client.post(path, files=files(), headers={'Idempotency-Key': 'upload-1'})
    assert replay.json()['import_id'] == body['import_id'] and len(calls) == 1
    changed = files()
    changed['brd'] = ('brd.txt', b'Changed requirements.', 'text/plain')
    assert s.client.post(path, files=changed, headers={'Idempotency-Key': 'upload-1'}).status_code == 409
    assert s.db.scalar(select(func.count()).select_from(Import)) == 1
    document = s.db.scalar(select(ImportDocument))
    assert PrivateStore().available(document.storage_key).read_bytes() in [f[1] for f in files().values()]


def test_document_grant_checks_identity_expiry_and_membership(owned, monkeypatch):
    s = owned
    install_transport(monkeypatch, extracted)
    prefix = f'/projects/{s.context.project_id}/imports'
    response = s.client.post(prefix, files=files())
    assert response.status_code == 201, response.text
    body = response.json()
    document = body['documents'][0]
    response = s.client.get(f'{prefix}/{body["import_id"]}/documents/{document["id"]}', follow_redirects=False)
    assert response.status_code == 302, response.text
    path = urlsplit(response.headers['location']).path
    download = s.client.get(path)
    assert download.status_code == 200 and download.content in [f[1] for f in files().values()]
    assert 'attachment' in download.headers['content-disposition']
    assert download.headers['x-content-type-options'] == 'nosniff'
    original = s.context.user
    main.app.dependency_overrides[current_user] = lambda: type('User', (), {'user_id': str(uuid4())})()
    assert s.client.get(path).status_code == 403
    main.app.dependency_overrides[current_user] = lambda: original
    token = path.rsplit('/', 1)[1]
    expired = signer().encrypt_at_time(signer().decrypt(token.encode()), int(time.time()) - 301).decode()
    assert s.client.get('/downloads/' + expired).status_code == 403
    from app.models import Project
    project = s.db.get(Project, s.context.project_id)
    project.owner_id = uuid4()
    s.db.commit()
    assert s.client.get(path).status_code == 404


def test_failed_extraction_retains_originals_without_fake_requirements(owned, monkeypatch):
    s = owned
    install_transport(monkeypatch, lambda request: httpx.Response(503))
    count = s.db.scalar(select(func.count()).select_from(Requirement))
    response = s.client.post(f'/projects/{s.context.project_id}/imports', files=files(), headers={'Idempotency-Key': 'retryable'})
    assert response.status_code == 503
    assert s.db.scalar(select(func.count()).select_from(Requirement)) == count
    assert s.db.scalar(select(Import)).status == 'pending'
    assert len(s.db.scalars(select(ImportDocument)).all()) == 2


def test_import_and_document_ownership_chain(owned):
    prefix = f'/projects/{owned.context.project_id}/imports'
    assert owned.client.get(prefix + '/' + str(uuid4())).status_code == 404
    assert owned.client.get(prefix + '/' + str(uuid4()) + '/documents/' + str(uuid4())).status_code == 404


@pytest.mark.parametrize('remote_status,expected', [('verified', True), ('rejected', False), ('inconclusive', False)])
def test_verification_sets_only_confirmed_revision(owned, monkeypatch, remote_status, expected):
    s = owned
    def ai(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={'request_id': body['request_id'], 'environment_id': body['environment_id'],
            'revision': body['revision'], 'status': remote_status, 'reason': 'success_observed' if expected else 'login_failed'})
    install_transport(monkeypatch, ai)
    response = s.client.post(f'/projects/{s.context.project_id}/environments/{s.eid}/verify')
    assert response.status_code == 202 and response.json()['status'] == remote_status, response.text
    s.db.expire_all()
    assert bool(s.db.get(Environment, s.eid).verified_at) == expected


def test_late_verification_cannot_verify_edited_environment(owned, monkeypatch):
    s = owned
    def ai(request):
        body = json.loads(request.content)
        environment = s.db.get(Environment, s.eid)
        environment.revision += 1
        s.db.commit()
        return httpx.Response(200, json={'request_id': body['request_id'], 'environment_id': body['environment_id'],
            'revision': body['revision'], 'status': 'verified', 'reason': 'success_observed'})
    install_transport(monkeypatch, ai)
    response = s.client.post(f'/projects/{s.context.project_id}/environments/{s.eid}/verify')
    assert response.status_code == 202 and response.json()['status'] == 'stale', response.text
    assert s.db.get(Environment, s.eid).verified_at is None


def test_verification_requires_admin(owned):
    s = owned
    main.app.dependency_overrides.pop(project_manage)
    main.app.dependency_overrides[project_access] = lambda: replace(s.context, role='member')
    assert s.client.post(f'/projects/{s.context.project_id}/environments/{s.eid}/verify').status_code == 403


def test_a1_evidence_is_authorized_fetched_verified_and_cached(owned, monkeypatch):
    s = owned
    run, _, envelope, _ = queue(s)
    evidence_id = str(uuid4())
    outcome = {'verdict': 'inconclusive', 'classification': 'execution_error', 'observed_behavior': 'Stub', 'actions': [],
        'criterion_verdicts': [{'criterion_id': envelope['requirements'][0]['criteria'][0]['id'], 'verdict': 'inconclusive',
            'rationale': 'Stub', 'source': 'engine', 'cited_evidence_ids': [evidence_id]}]}
    assert send(s, run, envelope, 'execution-events', event(envelope, 1, 'requirement.completed',
        {'run_id': run['id'], 'requirement_id': s.rid, 'outcome': outcome})).status_code == 202
    data = b'Actual retained stub evidence'
    calls = []
    def ai(request):
        calls.append(request)
        assert request.url.path == f'/v1/jobs/{envelope["job_id"]}/evidence/{evidence_id}'
        return httpx.Response(200, json={'id': evidence_id, 'job_id': envelope['job_id'], 'type': 'page_text',
            'media_type': 'text/plain', 'content_base64': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()})
    install_transport(monkeypatch, ai)
    response = s.client.get('/evidence/' + evidence_id, follow_redirects=False)
    assert response.status_code == 302, response.text
    assert s.client.get(urlsplit(response.headers['location']).path).content == data
    assert s.client.get('/evidence/' + evidence_id, follow_redirects=False).status_code == 302
    assert len(calls) == 1
    cached = s.db.get(Evidence, evidence_id)
    assert cached.captured_at is None
    PrivateStore().path(cached.storage_key).write_bytes(b'tampered')
    assert s.client.get('/evidence/' + evidence_id, follow_redirects=False).status_code == 409


def test_unknown_evidence_does_not_query_ai(owned, monkeypatch):
    install_transport(monkeypatch, lambda request: pytest.fail('Unreferenced evidence must not be fetched'))
    assert owned.client.get('/evidence/' + str(uuid4())).status_code == 404


def test_inconsistent_verification_proof_is_not_accepted(owned, monkeypatch):
    s = owned
    def ai(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={'request_id': body['request_id'], 'environment_id': body['environment_id'],
            'revision': body['revision'], 'status': 'verified', 'reason': 'login_failed'})
    install_transport(monkeypatch, ai)
    assert s.client.post(f'/projects/{s.context.project_id}/environments/{s.eid}/verify').status_code == 503
    assert s.db.get(Environment, s.eid).verified_at is None


def test_private_storage_rejects_paths_and_logs_redact_download_grants(owned):
    from app.core.observability import clean_text
    from app.core.errors import ServiceError
    with pytest.raises(ServiceError):
        PrivateStore().available('../.env')
    assert 'secret-link-value' not in clean_text('GET /downloads/secret-link-value HTTP/1.1')
