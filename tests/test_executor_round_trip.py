"""Opt-in HTTP round trip through the real aiservice with ENGINE=stub."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select, delete, func
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.deps import ProjectContext
from app.models import Project, Environment, AnalysisRun, AIUsage, Notification, Requirement, Result
from app.models.integration import Dispatch, Callback
from app.schemas.requirements import RequirementCreate, ApprovalRequest
from app.schemas.runs import RunCreate
from app.services import resources, analysis
from app.services.dispatch import dispatch_once


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url, process):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("Service exited; inspect test logs")
        try:
            if httpx.get(url).status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(.1)
    raise AssertionError("Service did not start")


def test_real_executor_stub_round_trip(tmp_path, monkeypatch):
    root = os.environ.get("AISERVICE_REPO")
    url = os.environ.get("BLINDSPOT_TEST_DATABASE_URL")
    if not root or not url:
        pytest.skip("Set AISERVICE_REPO and BLINDSPOT_TEST_DATABASE_URL for real HTTP integration")
    service = Path(root).resolve()
    interpreter = os.environ.get("AISERVICE_PYTHON", str(service / ".venv/bin/python"))
    be_port, ai_port = port(), port()
    settings = {"DATABASE_URL": url, "AI_SERVICE_URL": f"http://127.0.0.1:{ai_port}",
                "AI_API_KEY": "test-intake-secret", "AI_CALLBACK_BASE_URL": f"http://127.0.0.1:{be_port}/internal/v1",
                "DISPATCH_ENCRYPTION_KEY": Fernet.generate_key().decode(), "AI_ENGINE": "stub"}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    backend_env = {**os.environ, **settings}
    executor_env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'executor.db'}", "ENGINE": "stub",
                    "SERVICE_TOKEN": "test-intake-secret", "CALLBACK_POLL_SECONDS": "0.05",
                    "CALLBACK_ENCRYPTION_KEY": Fernet.generate_key().decode(), "PYTHONPATH": str(service)}
    subprocess.run([interpreter, "-m", "alembic", "upgrade", "head"], cwd=service, env=executor_env, check=True, capture_output=True)
    engine = create_engine(url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    project_id, user_id, environment_id = uuid4(), uuid4(), uuid4()
    processes = []
    try:
        with sessions() as db:
            db.add(Project(id=project_id, owner_id=user_id, name="Round trip", description="", created_at=analysis.now()))
            db.flush()
            db.add(Environment(id=environment_id, project_id=project_id, name="Staging", kind="staging",
                base_url="https://example.com", revision=1, created_at=analysis.now()))
            db.commit()
            context = ProjectContext(str(project_id), SimpleNamespace(user_id=str(user_id)), "owner")
            requirement = resources.create_requirement(db, context, RequirementCreate(title="Stub requirement", acceptance_criteria=[{"text": "Stub criterion"}]))
            resources.approve_requirement(db, context, requirement["id"], ApprovalRequest())
            run = analysis.create_run(db, context, str(environment_id), RunCreate(requirement_ids=[requirement["id"]]))
            runid = resources.uid(run["id"])
        with (tmp_path / "backend.log").open("w") as backend_log, (tmp_path / "executor.log").open("w") as executor_log:
            processes.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(be_port)], env=backend_env, stdout=backend_log, stderr=backend_log))
            processes.append(subprocess.Popen([interpreter, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(ai_port)], cwd=service, env=executor_env, stdout=executor_log, stderr=executor_log))
            wait_for(f"http://127.0.0.1:{be_port}/", processes[0])
            wait_for(f"http://127.0.0.1:{ai_port}/health", processes[1])
            assert dispatch_once(sessions)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with sessions() as db:
                    dispatch = db.scalar(select(Dispatch).where(Dispatch.run_id == runid))
                    finished = db.get(AnalysisRun, runid)
                    if dispatch.finalization and finished.status == "completed":
                        messages = db.scalars(select(Callback).where(Callback.run_id == runid)).all()
                        assert len(messages) >= 4
                        result = db.scalar(select(Result).where(Result.analysis_run_id == runid))
                        assert result.verdict == "inconclusive"
                        assert db.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.analysis_run_id == runid)) == 0
                        cost = analysis.usage_out(db, finished)
                        assert cost["cost_status"] == "final" and cost["estimated_cost_usd"] == 0
                        assert dispatch.status == "accepted"
                        return
                time.sleep(.1)
            raise AssertionError("Callbacks did not complete; inspect backend.log and executor.log")
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)
        with sessions.begin() as db:
            db.execute(delete(Notification).where(Notification.project_id == project_id))
            db.execute(delete(AnalysisRun).where(AnalysisRun.project_id == project_id))
            db.execute(delete(Requirement).where(Requirement.project_id == project_id))
            db.execute(delete(Environment).where(Environment.project_id == project_id))
            db.execute(delete(Project).where(Project.id == project_id))
        engine.dispose()
        get_settings.cache_clear()
