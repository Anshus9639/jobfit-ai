import asyncio
import os
import sys
from pathlib import Path

import fitz
import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Keep tests independent of the developer's shell/CI environment.
for _var in (
    "EMBEDDINGS_PROVIDER",
    "EMBEDDINGS_API_KEY",
    "EMBEDDINGS_BASE_URL",
    "EMBEDDINGS_MODEL",
    "HF_TOKEN",
    "HUGGINGFACE_API_KEY",
    "OPENAI_API_KEY",
):
    os.environ.pop(_var, None)

from app.main import app  # noqa: E402

RESUME_TEXT = """Jane Doe
jane@example.com | +1 555 123 4567

Skills
Python, React, Docker, PostgreSQL

Experience
Software Engineer at Acme. Built APIs with Python and React. Improved latency by 30%.

Projects
JobFit AI - resume analyzer.
- Worked on a resume analyzer used by 100 users.

Education
BS Computer Science
"""

JD_TEXT = """Software Engineer

Requirements
- 2+ years of experience with Python
- Experience with AWS and Docker
- Familiarity with PostgreSQL

Responsibilities
- Build backend services
- Collaborate with product teams
"""

EXPECTED_FIELDS = {
    "overall_score",
    "semantic_similarity",
    "keyword_match",
    "ats_score",
    "matched_skills",
    "missing_skills",
    "ats_issues",
    "recommendations",
    "recruiter_summary",
    "score_explanation",
    "resume_xray",
    "job_intelligence",
    "improvement_suggestions",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_pdf_bytes(text: str = RESUME_TEXT, pages: int = 1) -> bytes:
    doc = fitz.open()
    try:
        for _ in range(pages):
            page = doc.new_page()
            if text:
                page.insert_textbox(fitz.Rect(36, 36, 560, 800), text, fontsize=10)
        return doc.tobytes()
    finally:
        doc.close()


@pytest.fixture
def resume_pdf() -> bytes:
    return make_pdf_bytes()


class FakeEmbeddingProvider:
    """Deterministic in-process provider for API/scoring tests."""

    name = "fake"

    def __init__(self, vectors=((1.0, 0.0), (1.0, 0.0)), delay: float = 0.0, error=None):
        self._vectors = [list(v) for v in vectors]
        self.delay = delay
        self.error = error
        self.calls = []
        self.active = 0
        self.max_active = 0

    @property
    def is_configured(self) -> bool:
        return True

    async def embed(self, texts):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error is not None:
                raise self.error
            self.calls.append(list(texts))
            return [list(self._vectors[i % len(self._vectors)]) for i in range(len(texts))]
        finally:
            self.active -= 1

    async def aclose(self):
        return None


@pytest.fixture
async def api():
    """Running app + ASGI client, with the lifespan invoked per test."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", trust_env=False
        ) as client:
            yield app, client
