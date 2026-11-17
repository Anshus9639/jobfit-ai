import asyncio

import pytest

from app import config
from app.embeddings import (
    EmbeddingNotConfigured,
    EmbeddingProviderError,
    EmbeddingTimeout,
)
from app.schemas import AnalyzeResponse
from tests.conftest import (
    EXPECTED_FIELDS,
    FakeEmbeddingProvider,
    JD_TEXT,
    make_pdf_bytes,
)


def post_analyze(client, pdf_bytes, jd=JD_TEXT, content_type="application/pdf"):
    return client.post(
        "/api/analyze",
        files={"resume": ("resume.pdf", pdf_bytes, content_type)},
        data={"job_description": jd},
    )


@pytest.mark.anyio
async def test_full_response_matches_existing_contract(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()

    response = await post_analyze(client, resume_pdf)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == EXPECTED_FIELDS

    # Round-trip through the existing Pydantic model.
    AnalyzeResponse(**data)

    assert isinstance(data["overall_score"], int)
    assert isinstance(data["semantic_similarity"], int)
    assert isinstance(data["keyword_match"], int)
    assert isinstance(data["ats_score"], int)
    assert all(isinstance(item, str) for item in data["matched_skills"])
    assert all(isinstance(item, str) for item in data["missing_skills"])
    assert set(data["score_explanation"]) == {"strengths", "gaps", "explanation"}
    assert set(data["job_intelligence"]) == {
        "role",
        "technical_skills",
        "responsibilities",
        "requirements",
        "experience_level",
        "important_keywords",
    }
    assert set(data["resume_xray"][0]) == {"label", "status", "note"}
    assert set(data["improvement_suggestions"][0]) >= {"original", "suggestion", "why", "type"}


@pytest.mark.anyio
async def test_non_pdf_upload_is_rejected(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()

    response = await post_analyze(client, resume_pdf, content_type="text/plain")

    assert response.status_code == 400
    assert response.json()["detail"] == "Resume must be a PDF file."


@pytest.mark.anyio
async def test_empty_upload_is_rejected(api):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()

    response = await post_analyze(client, b"")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_oversized_upload_is_rejected_before_parsing(api):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()
    oversized = b"%PDF-1.4\n" + b"0" * (config.settings.max_pdf_size_bytes + 1)

    response = await post_analyze(client, oversized)

    assert response.status_code == 400
    assert "exceeds 5 mb" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_empty_job_description_is_rejected(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()

    response = await post_analyze(client, resume_pdf, jd="   ")

    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_overlong_job_description_is_rejected(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider()

    response = await post_analyze(client, resume_pdf, jd="x" * 20001)

    assert response.status_code == 400
    assert "too long" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_provider_timeout_returns_504_without_scores(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider(error=EmbeddingTimeout("upstream timeout"))

    response = await post_analyze(client, resume_pdf)

    assert response.status_code == 504
    body = response.json()
    assert "timeout" in body["detail"].lower()
    assert "overall_score" not in body


@pytest.mark.anyio
async def test_provider_failure_returns_502_without_scores(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider(
        error=EmbeddingProviderError("provider exploded")
    )

    response = await post_analyze(client, resume_pdf)

    assert response.status_code == 502
    body = response.json()
    assert "overall_score" not in body


@pytest.mark.anyio
async def test_missing_configuration_returns_503_without_scores(api, resume_pdf):
    app, client = api
    app.state.embedding_provider = FakeEmbeddingProvider(
        error=EmbeddingNotConfigured("Semantic similarity is not configured on the server.")
    )

    response = await post_analyze(client, resume_pdf)

    assert response.status_code == 503
    assert "overall_score" not in response.json()


@pytest.mark.anyio
async def test_concurrent_requests_are_bounded(api, resume_pdf):
    app, client = api
    app.state.analysis_semaphore = asyncio.Semaphore(2)
    fake = FakeEmbeddingProvider(delay=0.05)
    app.state.embedding_provider = fake

    responses = await asyncio.gather(
        *[post_analyze(client, resume_pdf) for _ in range(6)]
    )

    assert all(response.status_code == 200 for response in responses)
    assert 1 <= fake.max_active <= 2
    assert len(fake.calls) == 6


@pytest.mark.anyio
async def test_busy_service_returns_503_with_retry_after(api, resume_pdf, monkeypatch):
    app, client = api
    semaphore = asyncio.Semaphore(1)
    app.state.analysis_semaphore = semaphore
    app.state.embedding_provider = FakeEmbeddingProvider()
    monkeypatch.setattr(config.settings, "max_concurrency_wait_seconds", 0.01)

    await semaphore.acquire()
    try:
        response = await post_analyze(client, resume_pdf)
    finally:
        semaphore.release()

    assert response.status_code == 503
    assert response.headers.get("retry-after") == "5"
    assert "busy" in response.json()["detail"].lower()
