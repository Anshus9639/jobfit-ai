"""The app must boot without loading any ML model, without credentials, and without network."""

import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app

from conftest import FakeProvider, install_provider

BACKEND_DIR = Path(__file__).resolve().parent.parent
HEAVY_MODULES = ("torch", "sentence_transformers", "transformers", "sklearn", "scipy", "numpy")


def test_importing_the_app_loads_no_ml_libraries():
    code = (
        "import sys; import app.main; "
        f"loaded=[m for m in {HEAVY_MODULES!r} if m in sys.modules]; "
        "print(','.join(loaded)); sys.exit(1 if loaded else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True)
    assert result.returncode == 0, f"heavy modules imported at startup: {result.stdout.strip()} {result.stderr[-300:]}"


def test_requirements_exclude_heavyweight_packages():
    names = {
        re.split(r"[=<>\[ ]", line.strip(), maxsplit=1)[0].lower()
        for line in (BACKEND_DIR / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert not names & {"torch", "sentence-transformers", "scikit-learn", "numpy", "transformers", "scipy"}
    assert "httpx" in names  # needed at runtime by the embedding client


def test_startup_has_no_model_load_hook():
    source = (BACKEND_DIR / "app" / "main.py").read_text()
    assert "on_event" not in source and "get_model" not in source


def test_app_starts_serves_health_and_makes_no_network_call_without_config():
    provider = FakeProvider(lambda request: pytest.fail("startup must not call the embedding provider"))
    install_provider(provider, api_key=None)  # not configured

    with TestClient(app) as client:  # runs lifespan startup + shutdown
        assert client.get("/").json()["status"] == "ok"
        assert client.get("/health").json() == {"status": "healthy"}
        ready = client.get("/health/ready").json()

    assert ready == {"status": "degraded", "embedding_provider": "huggingface", "embedding_configured": False}
    assert provider.calls == 0


def test_ready_endpoint_reports_configured_without_calling_provider():
    provider = FakeProvider(lambda request: pytest.fail("readiness must not call the provider"))
    install_provider(provider)
    with TestClient(app) as client:
        ready = client.get("/health/ready").json()
    assert ready["status"] == "ready" and ready["embedding_configured"] is True
    assert provider.calls == 0
    assert "token" not in str(ready).lower()  # no credential material in the response


def test_startup_does_not_require_any_environment_variables(monkeypatch):
    # conftest already strips the embedding env; boot a clean interpreter to be sure.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EMBEDDING_", "HF_", "GEMINI_", "GOOGLE_"))}
    code = (
        "import sys; from fastapi.testclient import TestClient; from app.main import app; "
        "c=TestClient(app); c.__enter__(); r=c.get('/health'); "
        f"loaded=[m for m in {HEAVY_MODULES!r} if m in sys.modules]; "  # checked while the app is running
        "c.__exit__(None,None,None); "
        "assert r.status_code==200, r.text; "
        "assert not loaded, f'heavy modules loaded during startup: {loaded}'"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr[-500:]
