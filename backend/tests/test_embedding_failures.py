"""Provider timeouts, failures, retries and missing credentials.

Core rule under test: when semantic similarity cannot be computed, the request FAILS
with a clear error. No default, fallback or estimated score is ever returned.
"""

import asyncio
import json
import logging
import time

import httpx
import pytest

from app import embeddings
from app.embeddings import (
    EmbeddingAuthError, EmbeddingClient, EmbeddingNotConfigured, EmbeddingProviderError,
    EmbeddingRateLimited, EmbeddingResponseError, EmbeddingTimeout,
)
from app.main import app

from conftest import (
    TEST_TOKEN, FakeProvider, analyze_request, hf_ok_response, install_provider, make_client,
    make_pdf, make_settings, read_fixture, run_with_app, vectors_with_cosine,
)

PDF = make_pdf([read_fixture("strong_resume.txt")])
SCORE_FIELDS = ("overall_score", "semantic_similarity", "keyword_match", "ats_score")


def call_api():
    return run_with_app(app, analyze_request(app, PDF))


def embed(client, texts=("resume", "jd")):
    return asyncio.run(client.embed(list(texts)))


def assert_failed_without_any_score(response, status, retry_after=None):
    assert response.status_code == status, response.text
    body = response.json()
    assert list(body) == ["detail"], "failure responses must carry only an error message"
    assert not any(f in body for f in SCORE_FIELDS)
    assert TEST_TOKEN not in response.text
    if retry_after is not None:
        assert response.headers["retry-after"] == str(retry_after)


# --- missing / invalid configuration -------------------------------------------------

def test_missing_credentials_returns_503_without_any_network_call_or_score():
    provider = FakeProvider(lambda r: pytest.fail("must not call provider without credentials"))
    install_provider(provider, api_key=None)
    response = call_api()
    assert_failed_without_any_score(response, 503)
    assert "not configured" in response.json()["detail"]
    assert provider.calls == 0


def test_unknown_provider_is_a_configuration_error_not_a_crash():
    provider = FakeProvider()
    install_provider(provider, provider="does-not-exist")
    assert_failed_without_any_score(call_api(), 503)
    assert provider.calls == 0


def test_settings_read_keys_from_environment_only(monkeypatch):
    from app.config import load_embedding_settings
    assert load_embedding_settings().api_key is None
    monkeypatch.setenv("HF_TOKEN", "from-env")
    assert load_embedding_settings().api_key == "from-env"
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    assert load_embedding_settings().api_key is None  # HF token is not reused for Gemini
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    assert load_embedding_settings().api_key == "gem-key"


# --- timeouts and retries --------------------------------------------------------------

def test_persistent_timeout_retries_then_returns_504_with_no_score():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider = FakeProvider(handler)
    install_provider(provider, max_retries=2)
    response = call_api()
    assert_failed_without_any_score(response, 504)
    assert provider.calls == 3  # 1 attempt + 2 retries, then stop


def test_transient_5xx_is_retried_and_succeeds():
    answers = iter([httpx.Response(503, text="busy"), httpx.Response(502, text="bad gateway"), hf_ok_response(0.5)])
    provider = FakeProvider(lambda r: next(answers))
    install_provider(provider)
    response = call_api()
    assert response.status_code == 200 and provider.calls == 3
    assert response.json()["semantic_similarity"] == 50


def test_network_error_is_retried():
    answers = iter([httpx.ConnectError("refused"), hf_ok_response(0.5)])

    def handler(request):
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value

    provider = FakeProvider(handler)
    install_provider(provider)
    assert call_api().status_code == 200 and provider.calls == 2


def test_persistent_5xx_returns_502_after_bounded_retries():
    provider = FakeProvider(lambda r: httpx.Response(500, text="boom"))
    install_provider(provider, max_retries=2)
    assert_failed_without_any_score(call_api(), 502)
    assert provider.calls == 3


def test_rate_limit_honours_retry_after_then_succeeds():
    answers = iter([httpx.Response(429, headers={"retry-after": "2"}), hf_ok_response(0.5)])
    provider = FakeProvider(lambda r: next(answers))
    client = install_provider(provider)
    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    client._sleep = record_sleep
    assert call_api().status_code == 200
    assert delays == [2.0]


def test_persistent_rate_limit_returns_503_with_retry_after_header():
    provider = FakeProvider(lambda r: httpx.Response(429, headers={"retry-after": "30"}))
    install_provider(provider, max_retries=1, total_timeout_seconds=20.0)
    # 30s wait would exceed the 20s deadline, so it must give up immediately rather than wait.
    response = call_api()
    assert_failed_without_any_score(response, 503, retry_after=30)
    assert provider.calls == 1


def test_model_loading_503_uses_estimated_time_as_the_wait():
    answers = iter([httpx.Response(503, json={"error": "loading", "estimated_time": 1.5}), hf_ok_response()])
    provider = FakeProvider(lambda r: next(answers))
    client = install_provider(provider)
    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    client._sleep = record_sleep
    embed(client)
    assert delays == [1.5]


def test_overall_deadline_bounds_total_time_even_with_many_retries():
    async def slow_503(request):
        await asyncio.sleep(0.15)
        return httpx.Response(503, text="busy")

    provider = FakeProvider(slow_503)
    client = make_client(provider, max_retries=50, timeout_seconds=1.0, total_timeout_seconds=0.6)
    client._sleep = asyncio.sleep  # real (short) backoff, so the deadline is what stops it
    started = time.monotonic()
    with pytest.raises(EmbeddingProviderError):
        embed(client)
    assert time.monotonic() - started < 2.0
    assert provider.calls < 10


# --- non-retryable failures -------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403])
def test_bad_credentials_are_not_retried_and_never_leaked(status):
    provider = FakeProvider(lambda r: httpx.Response(status, text=f"invalid token {TEST_TOKEN}"))
    install_provider(provider)
    response = call_api()
    assert_failed_without_any_score(response, 503)
    assert "credentials" in response.json()["detail"]
    assert provider.calls == 1


def test_client_errors_are_not_retried():
    provider = FakeProvider(lambda r: httpx.Response(400, text="bad request"))
    install_provider(provider)
    assert_failed_without_any_score(call_api(), 502)
    assert provider.calls == 1


def test_provider_error_bodies_and_keys_never_reach_logs(caplog):
    provider = FakeProvider(lambda r: httpx.Response(500, text=f"upstream said token={TEST_TOKEN}"))
    install_provider(provider)
    with caplog.at_level(logging.DEBUG):
        call_api()
    assert TEST_TOKEN not in caplog.text
    assert "Anshu" not in caplog.text  # resume text is never logged


# --- malformed 200 responses -------------------------------------------------------------

BAD_PAYLOADS = {
    "not json": httpx.Response(200, text="<html>gateway</html>"),
    "wrong count": httpx.Response(200, json=[[0.1, 0.2]]),
    "token-level 3d output": httpx.Response(200, json=[[[0.1, 0.2]], [[0.3, 0.4]]]),
    "error object": httpx.Response(200, json={"error": "oops"}),
    "empty vector": httpx.Response(200, json=[[], []]),
    "strings in vector": httpx.Response(200, json=[["a", "b"], ["c", "d"]]),
    "null in vector": httpx.Response(200, json=[[0.1, None], [0.3, 0.4]]),
    "dimension mismatch": httpx.Response(200, json=[[0.1, 0.2], [0.3, 0.4, 0.5]]),
    "zero vector": httpx.Response(200, json=[[0.0, 0.0], [0.3, 0.4]]),
    "NaN": httpx.Response(200, content=b"[[NaN, 0.1], [0.3, 0.4]]", headers={"content-type": "application/json"}),
    "infinity": httpx.Response(200, content=b"[[Infinity, 0.1], [0.3, 0.4]]", headers={"content-type": "application/json"}),
}


@pytest.mark.parametrize("name", sorted(BAD_PAYLOADS))
def test_malformed_provider_response_fails_the_request_not_the_score(name):
    provider = FakeProvider(lambda r: BAD_PAYLOADS[name])
    install_provider(provider)
    assert_failed_without_any_score(call_api(), 502)
    assert provider.calls == 1  # a bad payload is not retried


# --- provider adapters ---------------------------------------------------------------------

def test_huggingface_request_shape_and_auth_header():
    provider = FakeProvider()
    client = make_client(provider)
    embed(client, ("hello resume", "hello jd"))
    request = provider.requests[0]
    assert request.url.host == "router.huggingface.co"
    assert request.url.path == "/hf-inference/models/BAAI/bge-small-en-v1.5/pipeline/feature-extraction"
    assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
    assert json.loads(request.content) == {"inputs": ["hello resume", "hello jd"], "truncate": True}


def test_gemini_request_shape_and_response_parsing():
    def handler(request):
        vecs = vectors_with_cosine(0.4)
        return httpx.Response(200, json={"embeddings": [{"values": v} for v in vecs]})

    provider = FakeProvider(handler)
    client = make_client(provider, provider="gemini", model="gemini-embedding-2", api_key="gem-key")
    vectors = embed(client, ("a", "b"))
    request = provider.requests[0]
    assert request.url.path == "/v1beta/models/gemini-embedding-2:batchEmbedContents"
    assert request.headers["x-goog-api-key"] == "gem-key"
    body = json.loads(request.content)
    assert [r["content"]["parts"][0]["text"] for r in body["requests"]] == ["a", "b"]
    assert len(vectors) == 2


def test_url_override_allows_provider_endpoint_changes_without_a_code_change():
    provider = FakeProvider()
    client = make_client(provider, api_url="https://embeddings.example.test/v2/embed")
    embed(client)
    assert str(provider.requests[0].url) == "https://embeddings.example.test/v2/embed"


def test_inputs_are_truncated_before_leaving_the_server():
    provider = FakeProvider()
    client = make_client(provider, max_input_chars=500)
    embed(client, ("a" * 10_000, "b" * 10_000))
    sent = json.loads(provider.requests[0].content)["inputs"]
    assert [len(t) for t in sent] == [500, 500]


# --- client lifecycle -------------------------------------------------------------------------

def test_http_client_is_created_exactly_once_under_concurrent_first_use():
    created = []
    provider = FakeProvider()

    def factory():
        created.append(1)
        return httpx.AsyncClient(transport=provider.transport())

    client = EmbeddingClient(make_settings(), http_client_factory=factory)

    async def burst():
        await asyncio.gather(*(client.embed(["r", "j"]) for _ in range(25)))

    asyncio.run(burst())
    assert len(created) == 1
    assert provider.calls == 25
