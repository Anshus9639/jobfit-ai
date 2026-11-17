import asyncio
import json
import sys
import time
import types

import httpx
import pytest

from app import embeddings
from app.config import Settings
from app.embeddings import (
    EmbeddingNotConfigured,
    EmbeddingProviderError,
    EmbeddingTimeout,
    HuggingFaceEmbeddingProvider,
    LocalSentenceTransformerProvider,
    OpenAICompatibleEmbeddingProvider,
)

HF_URL = (
    "https://example.test/models/sentence-transformers/all-MiniLM-L6-v2"
    "/pipeline/feature-extraction"
)


def make_settings(**overrides) -> Settings:
    settings = Settings.from_env()
    settings.embeddings_provider = "huggingface"
    settings.embeddings_api_key = "test-key"
    settings.embeddings_base_url = "https://example.test"
    settings.embeddings_model = "sentence-transformers/all-MiniLM-L6-v2"
    settings.embeddings_timeout_seconds = 5.0
    settings.embeddings_max_retries = 0
    settings.embeddings_retry_backoff_seconds = 0.0
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)


@pytest.mark.anyio
async def test_huggingface_success():
    def handler(request):
        assert str(request.url) == HF_URL
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["inputs"] == ["resume", "jd"]
        return httpx.Response(200, json=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(), client=client)
    try:
        vectors = await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.anyio
async def test_huggingface_pools_token_level_embeddings():
    def handler(request):
        # 3D output: one [tokens, dim] block per input.
        return httpx.Response(200, json=[[[1.0, 0.0], [3.0, 0.0]], [[0.0, 2.0], [0.0, 4.0]]])

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(), client=client)
    try:
        vectors = await provider.embed(["a", "b"])
    finally:
        await client.aclose()

    assert vectors == [[2.0, 0.0], [0.0, 3.0]]


@pytest.mark.anyio
async def test_timeout_retries_then_raises_timeout():
    calls = []

    def handler(request):
        calls.append(request.url)
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(embeddings_max_retries=2), client=client)
    try:
        with pytest.raises(EmbeddingTimeout) as exc_info:
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert len(calls) == 3
    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_retryable_status_then_success():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "model loading"})
        return httpx.Response(200, json=[[1.0, 0.0], [0.0, 1.0]])

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(embeddings_max_retries=1), client=client)
    try:
        vectors = await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert calls["count"] == 2
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.anyio
async def test_auth_failure_is_not_retried_and_does_not_leak_key():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(401, json={"error": "invalid token"})

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(
        make_settings(embeddings_api_key="super-secret-token", embeddings_max_retries=2),
        client=client,
    )
    try:
        with pytest.raises(EmbeddingProviderError) as exc_info:
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert calls["count"] == 1
    assert "credentials" in str(exc_info.value).lower()
    assert "super-secret-token" not in str(exc_info.value)


@pytest.mark.anyio
async def test_exhausted_retries_raise_provider_error():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(500, json={"error": "boom"})

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(embeddings_max_retries=2), client=client)
    try:
        with pytest.raises(EmbeddingProviderError):
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert calls["count"] == 3


@pytest.mark.anyio
async def test_malformed_response_is_rejected():
    client = make_client(lambda request: httpx.Response(200, json={"unexpected": True}))
    provider = HuggingFaceEmbeddingProvider(make_settings(), client=client)
    try:
        with pytest.raises(EmbeddingProviderError):
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_inconsistent_dimensions_are_rejected():
    client = make_client(lambda request: httpx.Response(200, json=[[0.1, 0.2], [0.3]]))
    provider = HuggingFaceEmbeddingProvider(make_settings(), client=client)
    try:
        with pytest.raises(EmbeddingProviderError):
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_non_finite_values_are_rejected():
    client = make_client(lambda request: httpx.Response(200, json=[[float("nan")], [0.0]]))
    provider = HuggingFaceEmbeddingProvider(make_settings(), client=client)
    try:
        with pytest.raises(EmbeddingProviderError):
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_missing_key_fails_without_network_call():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(200, json=[[1.0], [1.0]])

    client = make_client(handler)
    provider = HuggingFaceEmbeddingProvider(make_settings(embeddings_api_key=None), client=client)
    try:
        with pytest.raises(EmbeddingNotConfigured):
            await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert calls["count"] == 0


@pytest.mark.anyio
async def test_openai_compatible_provider_orders_by_index():
    def handler(request):
        assert str(request.url) == "https://example.test/embeddings"
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small"
        assert body["input"] == ["resume", "jd"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    client = make_client(handler)
    settings = make_settings(
        embeddings_provider="openai",
        embeddings_model="text-embedding-3-small",
    )
    provider = OpenAICompatibleEmbeddingProvider(settings, client=client)
    try:
        vectors = await provider.embed(["resume", "jd"])
    finally:
        await client.aclose()

    assert vectors == [[0.1, 0.2], [0.5, 0.6]]


@pytest.mark.anyio
async def test_local_provider_reports_missing_optional_dependencies(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    monkeypatch.setattr(embeddings, "_local_model", None)

    provider = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")
    with pytest.raises(EmbeddingNotConfigured):
        await provider.embed(["resume", "jd"])


@pytest.mark.anyio
async def test_local_model_is_initialized_exactly_once(monkeypatch):
    init_calls = {"count": 0}

    class FakeArray:
        def __init__(self, data):
            self._data = data

        def tolist(self):
            return self._data

    class FakeSentenceTransformer:
        def __init__(self, model_name):
            init_calls["count"] += 1
            time.sleep(0.05)

        def encode(self, texts, normalize_embeddings=True):
            return FakeArray([[1.0, 0.0] for _ in texts])

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(embeddings, "_local_model", None)

    provider = LocalSentenceTransformerProvider("all-MiniLM-L6-v2")

    await asyncio.gather(*[provider.embed(["resume", "jd"]) for _ in range(5)])

    assert init_calls["count"] == 1
