"""Shared test helpers: fixtures, PDF builders, and a controllable fake embedding provider.

The fake provider is a *test double for the HTTP API only*. Tests choose the vectors it
returns (so the expected cosine is known); the application never fabricates scores.
"""

import asyncio
import json
import math
from pathlib import Path
from typing import Callable, List, Optional

import fitz
import httpx
import pytest

from app import embeddings, limits
from app.config import EmbeddingSettings
from app.embeddings import EmbeddingClient

FIXTURES = Path(__file__).parent / "fixtures"

TEST_TOKEN = "hf_test_token_DO_NOT_LEAK_123"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text().strip()


def make_pdf(pages: List[str], encrypt: bool = False) -> bytes:
    """Build a text PDF; each string in `pages` is one page, one line per text line."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        y = 40
        for line in text.splitlines():
            page.insert_text((36, y), line, fontsize=7)
            y += 9
    kwargs = {"encryption": fitz.PDF_ENCRYPT_AES_256, "user_pw": "secret", "owner_pw": "secret"} if encrypt else {}
    data = doc.tobytes(**kwargs)
    doc.close()
    return data


def make_blank_pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def vectors_with_cosine(cosine: float, dim: int = 384) -> List[List[float]]:
    """Two vectors whose cosine similarity is exactly `cosine` (|cosine| <= 1)."""
    a = [1.0] + [0.0] * (dim - 1)
    b = [cosine, math.sqrt(max(0.0, 1 - cosine * cosine))] + [0.0] * (dim - 2)
    return [a, b]


def hf_ok_response(cosine: float = 0.625) -> httpx.Response:
    return httpx.Response(200, json=vectors_with_cosine(cosine))


class FakeProvider:
    """Wraps a handler, counting calls and in-flight concurrency."""

    def __init__(self, handler: Optional[Callable] = None):
        self.handler = handler or (lambda request: hf_ok_response())
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.requests: List[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.requests.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            result = self.handler(request)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        finally:
            self.in_flight -= 1

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def make_settings(**overrides) -> EmbeddingSettings:
    values = dict(
        provider="huggingface",
        api_key=TEST_TOKEN,
        model="BAAI/bge-small-en-v1.5",
        api_url=None,
        timeout_seconds=5.0,
        total_timeout_seconds=20.0,
        max_retries=2,
        max_input_chars=6000,
    )
    values.update(overrides)
    return EmbeddingSettings(**values)


def make_client(fake: FakeProvider, **settings_overrides) -> EmbeddingClient:
    client = EmbeddingClient(
        make_settings(**settings_overrides),
        http_client_factory=lambda: httpx.AsyncClient(transport=fake.transport()),
    )

    async def no_sleep(_delay):  # keep retry tests fast; tests that care patch it themselves
        return None

    client._sleep = no_sleep
    return client


@pytest.fixture(autouse=True)
def _isolated_singletons(monkeypatch):
    """Every test starts with no cached client/gate and no inherited configuration."""
    for var in (
        "EMBEDDING_PROVIDER", "EMBEDDING_API_KEY", "EMBEDDING_MODEL", "EMBEDDING_API_URL",
        "HF_TOKEN", "HUGGINGFACE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "MAX_CONCURRENT_ANALYSES", "MAX_WAITING_ANALYSES", "ANALYSIS_WAIT_TIMEOUT_SECONDS",
        "MAX_PDF_PAGES", "MAX_RESUME_CHARS",
    ):
        monkeypatch.delenv(var, raising=False)
    embeddings.set_embedding_client(None)
    limits.reset_gate()
    yield
    embeddings.set_embedding_client(None)
    limits.reset_gate()


def install_provider(fake: FakeProvider, **settings_overrides) -> EmbeddingClient:
    client = make_client(fake, **settings_overrides)
    embeddings.set_embedding_client(client)
    return client


def analyze_request(app, pdf: bytes, jd: str = None, content_type: str = "application/pdf", headers=None):
    """Return a coroutine factory performing POST /api/analyze through the ASGI app."""
    jd = jd if jd is not None else read_fixture("strong_jd.txt")

    async def run(client: httpx.AsyncClient):
        return await client.post(
            "/api/analyze",
            files={"resume": ("resume.pdf", pdf, content_type)},
            data={"job_description": jd},
            headers=headers,
        )

    return run


def run_with_app(app, coro_fn):
    """Run `coro_fn(client)` against the app in a fresh event loop; returns its result."""

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await coro_fn(client)

    return asyncio.run(main())


def golden():
    return json.loads((FIXTURES / "golden_reports.json").read_text())
