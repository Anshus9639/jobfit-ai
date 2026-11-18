"""Hardening of the embedding client: wall-clock deadline, response cap, log hygiene,
vector normalization and provider-configuration validation."""

import asyncio
import json
import logging
import math
import time

import httpx
import pytest

from app import analyzer, embeddings
from app.embeddings import (
    EmbeddingClient, EmbeddingProviderError, EmbeddingResponseError, EmbeddingTimeout,
    cosine_similarity, validate_vectors,
)
from app.main import app

from conftest import (
    TEST_TOKEN, FakeProvider, analyze_request, hf_ok_response, install_provider, make_client,
    make_pdf, make_settings, read_fixture, run_with_app,
)

PDF = make_pdf([read_fixture("strong_resume.txt")])


def embed(client, texts=("resume", "jd")):
    return asyncio.run(client.embed(list(texts)))


class Stream(httpx.AsyncByteStream):
    def __init__(self, gen_factory):
        self._factory = gen_factory

    async def __aiter__(self):
        async for chunk in self._factory():
            yield chunk


# --- 1. strict wall-clock timeout ------------------------------------------------------

def test_trickling_response_is_cut_off_by_wall_clock_deadline():
    """Each chunk arrives well inside any per-read timeout, but the body never ends."""
    async def trickle():
        yield b"["
        while True:
            await asyncio.sleep(0.05)
            yield b" "

    provider = FakeProvider(lambda r: httpx.Response(200, stream=Stream(trickle)))
    client = make_client(provider, timeout_seconds=1.0, total_timeout_seconds=1.0, max_retries=0)
    started = time.monotonic()
    with pytest.raises(EmbeddingTimeout):
        embed(client)
    assert time.monotonic() - started < 2.0


def test_wall_clock_covers_a_stalled_handler_and_each_attempt_is_bounded():
    async def stall(request):
        await asyncio.sleep(30)

    provider = FakeProvider(stall)
    client = make_client(provider, timeout_seconds=1.0, total_timeout_seconds=2.5, max_retries=5)
    started = time.monotonic()
    with pytest.raises(EmbeddingTimeout):
        embed(client)
    assert time.monotonic() - started < 4.0


# --- 2. response byte cap --------------------------------------------------------------

def test_oversized_streamed_body_is_aborted_early():
    sent = 0

    async def endless():
        nonlocal sent
        while True:
            sent += 64 * 1024
            yield b"x" * (64 * 1024)

    provider = FakeProvider(lambda r: httpx.Response(200, stream=Stream(endless)))
    client = make_client(provider, max_response_bytes=4096, max_retries=0)
    with pytest.raises(EmbeddingResponseError):
        embed(client)
    assert sent <= 4 * 64 * 1024, "must stop reading soon after the cap, not drain the stream"


def test_declared_content_length_over_cap_is_rejected_without_reading_body():
    read = False

    async def body():
        nonlocal read
        read = True
        yield b"[]"

    response = lambda r: httpx.Response(200, headers={"content-length": "999999999"}, stream=Stream(body))
    client = make_client(FakeProvider(response), max_response_bytes=4096, max_retries=0)
    with pytest.raises(EmbeddingResponseError):
        embed(client)
    assert read is False


def test_body_under_cap_is_accepted():
    client = make_client(FakeProvider(), max_response_bytes=1024 * 1024)
    assert len(embed(client)) == 2


def test_error_bodies_are_never_buffered_beyond_the_peek():
    """A huge 500 body must not be read at all."""
    consumed = 0

    async def huge():
        nonlocal consumed
        for _ in range(1000):
            consumed += 1
            yield b"y" * 65536

    client = make_client(FakeProvider(lambda r: httpx.Response(500, stream=Stream(huge))), max_retries=0)
    with pytest.raises(EmbeddingProviderError):
        embed(client)
    assert consumed == 0


def test_huge_503_body_peek_is_bounded():
    consumed = 0

    async def huge():
        nonlocal consumed
        for _ in range(1000):
            consumed += 1
            yield b"y" * 65536

    client = make_client(FakeProvider(lambda r: httpx.Response(503, stream=Stream(huge))), max_retries=0)
    with pytest.raises(EmbeddingProviderError):
        embed(client)
    assert consumed <= 1


def test_estimated_time_from_small_503_body_still_honoured():
    provider = FakeProvider(lambda r: httpx.Response(503, json={"estimated_time": 7}))
    client = make_client(provider, max_retries=0)
    with pytest.raises(EmbeddingProviderError) as info:
        embed(client)
    assert info.value.retry_after == 7


def test_redirects_are_not_followed():
    client = EmbeddingClient(make_settings())
    http = asyncio.run(client._get_http())
    assert http.follow_redirects is False


def test_redirect_response_is_an_error_not_followed():
    provider = FakeProvider(lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"}))
    client = make_client(provider, max_retries=0)
    with pytest.raises(EmbeddingProviderError):
        embed(client)
    assert provider.calls == 1


# --- 3. no upstream text / user content in logs or errors -------------------------------

SENTINEL = "UPSTREAM-SECRET-BODY-12345"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
def test_upstream_error_text_never_logged_or_returned(status, caplog):
    provider = FakeProvider(lambda r: httpx.Response(status, text=f"{SENTINEL} echo {TEST_TOKEN}"))
    install_provider(provider, max_retries=1)
    with caplog.at_level(logging.DEBUG):
        response = run_with_app(app, analyze_request(app, PDF))
    assert response.status_code >= 400
    assert SENTINEL not in caplog.text and SENTINEL not in response.text
    assert TEST_TOKEN not in caplog.text and TEST_TOKEN not in response.text


def test_invalid_json_body_text_is_not_logged(caplog):
    provider = FakeProvider(lambda r: httpx.Response(200, text=f"not json {SENTINEL}"))
    install_provider(provider, max_retries=0)
    with caplog.at_level(logging.DEBUG):
        response = run_with_app(app, analyze_request(app, PDF))
    assert response.status_code == 502
    assert SENTINEL not in caplog.text and SENTINEL not in response.text


def test_provider_exception_text_is_not_logged(caplog):
    def boom(request):
        raise httpx.ConnectError(f"connect failed {SENTINEL}")

    install_provider(FakeProvider(boom), max_retries=0)
    with caplog.at_level(logging.DEBUG):
        response = run_with_app(app, analyze_request(app, PDF))
    assert response.status_code in (502, 503, 504)
    assert SENTINEL not in caplog.text and SENTINEL not in response.text


def test_unexpected_error_logs_class_only_and_returns_generic_500(monkeypatch, caplog):
    resume_marker = "PRIVATE-RESUME-CONTENT-98765"

    async def explode(resume_text, jd):
        raise ValueError(f"bad data: {resume_text[:20]} {resume_marker}")

    monkeypatch.setattr("app.main.run_analysis", explode)
    install_provider(FakeProvider())
    with caplog.at_level(logging.DEBUG):
        response = run_with_app(app, analyze_request(app, PDF, jd=f"JD-MARKER {resume_marker}"))
    assert response.status_code == 500
    assert response.json() == {"detail": "Analysis failed unexpectedly. Please try again."}
    assert "ValueError" in caplog.text
    assert resume_marker not in caplog.text and "JD-MARKER" not in caplog.text
    assert resume_marker not in response.text


def test_error_detail_is_truncated():
    assert len(embeddings.EmbeddingError("x" * 5000).detail) <= 200


# --- 6. vector normalization and non-finite rejection -----------------------------------

def test_huge_magnitude_vectors_do_not_overflow_to_a_perfect_score():
    a = [1e200] + [0.0] * 383
    b = [1e200] + [0.0] * 383
    assert cosine_similarity(a, b) == pytest.approx(1.0)
    c = [0.0, 1e200] + [0.0] * 382
    assert cosine_similarity(a, c) == pytest.approx(0.0)


def test_scaled_vectors_have_the_same_cosine():
    a, b = [1.0, 2.0, 3.0], [3.0, 2.0, 1.0]
    base = cosine_similarity(a, b)
    assert cosine_similarity([x * 1e-30 for x in a], [x * 1e30 for x in b]) == pytest.approx(base)


@pytest.mark.parametrize("bad", [[float("nan"), 1.0], [float("inf"), 1.0], [0.0, 0.0], []])
def test_non_finite_zero_or_empty_vectors_are_rejected(bad):
    with pytest.raises(EmbeddingResponseError):
        cosine_similarity(bad, [1.0, 1.0] if bad else [])
    with pytest.raises(EmbeddingResponseError):
        validate_vectors([bad, [1.0, 1.0]], 2)


def test_overflowing_json_number_is_rejected_through_the_client():
    body = b"[[1e999, 1.0], [1.0, 1.0]]"  # json.loads turns 1e999 into inf
    client = make_client(FakeProvider(lambda r: httpx.Response(200, content=body)), max_retries=0)
    with pytest.raises(EmbeddingResponseError):
        embed(client)


def test_semantic_score_stays_in_range_for_extreme_vectors():
    big = [[1e200, 0.0], [1e200, 0.0]]
    client = make_client(FakeProvider(lambda r: httpx.Response(200, json=big)))
    embeddings.set_embedding_client(client)
    score = asyncio.run(analyzer.compute_semantic_similarity("a", "b"))
    assert score == pytest.approx(100.0)  # genuinely identical direction, not an overflow artifact
    opposite = [[1e200, 0.0], [0.0, 1e200]]
    client2 = make_client(FakeProvider(lambda r: httpx.Response(200, json=opposite)))
    embeddings.set_embedding_client(client2)
    assert asyncio.run(analyzer.compute_semantic_similarity("a", "b")) == pytest.approx(0.0)


@pytest.mark.parametrize("raw", [[[True, 1.0], [1.0, 1.0]], [["a", 1.0], [1.0, 1.0]], [[1.0], [1.0, 1.0]], "x"])
def test_malformed_vectors_are_rejected(raw):
    with pytest.raises(EmbeddingResponseError):
        validate_vectors(raw, 2)


# --- 8. configuration and HTTPS validation ---------------------------------------------

def problem(**overrides):
    return EmbeddingClient(make_settings(**overrides)).configuration_problem()


@pytest.mark.parametrize("url", [
    "http://api.example.com/embed",
    "ftp://api.example.com/embed",
    "https://user:pass@api.example.com/embed",
    "https:///nohost",
    "api.example.com/embed",
    "https://api.example.com:notaport/x",
])
def test_unsafe_endpoint_urls_are_rejected_without_echoing_them(url):
    message = problem(api_url=url)
    assert message and "EMBEDDING_API_URL" in message
    assert "pass" not in message and "api.example.com" not in message


@pytest.mark.parametrize("url", ["https://api.example.com/embed", "http://localhost:8080/x", "http://127.0.0.1:9/x"])
def test_acceptable_endpoint_urls(url):
    assert problem(api_url=url) is None


@pytest.mark.parametrize("model", ["bad model", "a/b/../..;x", "x" * 200, "../etc", "ok\nnewline"])
def test_invalid_model_ids_are_rejected(model):
    message = problem(model=model)
    assert message and "EMBEDDING_MODEL" in message


@pytest.mark.parametrize("key", ["has space", "tab\tkey", "new\nline", "ключ", "x" * 600])
def test_malformed_api_keys_are_rejected_without_echo(key):
    message = problem(api_key=key)
    assert message and key not in message


def test_unconfigured_endpoint_makes_analyze_return_503():
    install_provider(FakeProvider(), api_url="http://api.example.com/embed")
    response = run_with_app(app, analyze_request(app, PDF))
    assert response.status_code == 503
    assert "api.example.com" not in response.text
