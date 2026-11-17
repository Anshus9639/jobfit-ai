import sys

import pytest

from app import config
from app.embeddings import HuggingFaceEmbeddingProvider
from tests.conftest import JD_TEXT


def test_app_import_does_not_pull_in_ml_stack():
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules
    assert "sklearn" not in sys.modules


@pytest.mark.anyio
async def test_health_is_available_without_credentials(api, monkeypatch):
    app, client = api
    monkeypatch.setattr(config.settings, "embeddings_api_key", None)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["semantic_provider"] == "huggingface"
    assert body["semantic_configured"] is False


@pytest.mark.anyio
async def test_startup_does_not_require_an_api_key(api, monkeypatch):
    # Reaching this point proves the lifespan completed without a key.
    monkeypatch.setattr(config.settings, "embeddings_api_key", None)
    app, client = api

    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules
    assert (await client.get("/")).status_code == 200


@pytest.mark.anyio
async def test_analyze_without_credentials_returns_503_and_no_score(api, resume_pdf, monkeypatch):
    app, client = api
    monkeypatch.setattr(config.settings, "embeddings_api_key", None)
    provider = HuggingFaceEmbeddingProvider(config.settings)
    app.state.embedding_provider = provider

    try:
        response = await client.post(
            "/api/analyze",
            files={"resume": ("resume.pdf", resume_pdf, "application/pdf")},
            data={"job_description": JD_TEXT},
        )
    finally:
        await provider.aclose()

    assert response.status_code == 503
    body = response.json()
    assert "not configured" in body["detail"].lower()
    assert "overall_score" not in body
    assert "semantic_similarity" not in body
