"""
main.py
FastAPI application entrypoint for JobFit AI backend.

The process no longer loads PyTorch or a local embedding model. Semantic
similarity is served by a hosted embedding API; keyword and ATS analysis run
locally. Request concurrency and upload sizes are bounded to keep peak memory
predictable on small instances.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from . import config
from .analyzer import run_analysis
from .embeddings import (
    EmbeddingError,
    EmbeddingNotConfigured,
    EmbeddingProviderError,
    EmbeddingTimeout,
    build_embedding_provider,
)
from .pdf_parser import extract_text_from_pdf
from .schemas import AnalyzeResponse

logger = logging.getLogger("jobfit")

UPLOAD_CHUNK_BYTES = 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = config.settings

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.embeddings_timeout_seconds),
        limits=httpx.Limits(
            max_connections=max(8, settings.max_concurrent_analyses * 2),
            max_keepalive_connections=max(4, settings.max_concurrent_analyses),
        ),
        # Outbound provider calls go direct; inherited proxy settings on small
        # hosts are a common source of opaque connection failures.
        trust_env=False,
    )
    provider = build_embedding_provider(settings, client=client)

    app.state.http_client = client
    app.state.embedding_provider = provider
    app.state.analysis_semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)

    logger.info(
        "JobFit AI ready (provider=%s, configured=%s, model=%s, max_concurrency=%d)",
        provider.name,
        provider.is_configured,
        settings.embeddings_model,
        settings.max_concurrent_analyses,
    )
    if not provider.is_configured:
        logger.warning(
            "Semantic similarity is not configured; /api/analyze will return 503 "
            "until EMBEDDINGS_API_KEY is set."
        )

    try:
        yield
    finally:
        await provider.aclose()
        await client.aclose()


settings = config.settings

app = FastAPI(
    title="JobFit AI",
    description="AI/NLP resume-to-job-description match analyzer (ATS-style, not an official ATS).",
    version="1.1.0",
    lifespan=lifespan,
)

# CORS: allow the configured frontend origin(s). Defaults to "*" for local dev.
allowed_origins = settings.allowed_origins
origins = [o.strip() for o in allowed_origins.split(",")] if allowed_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,  # no cookies/auth used; avoids invalid combo with wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "JobFit AI backend"}


@app.get("/health")
def health(request: Request):
    provider = getattr(request.app.state, "embedding_provider", None)
    return {
        "status": "healthy",
        "semantic_provider": provider.name if provider else None,
        "semantic_configured": provider.is_configured if provider else False,
    }


async def _read_upload_bounded(upload: UploadFile, limit_bytes: int) -> bytes:
    """Read an upload in chunks, aborting as soon as it exceeds the size limit."""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit_bytes:
            limit_mb = limit_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"Resume PDF exceeds {limit_mb} MB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _busy_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="The analysis service is busy. Please retry in a few seconds.",
        headers={"Retry-After": "5"},
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: Request,
    resume: UploadFile = File(...),
    job_description: str = Form(...),
):
    # --- Validate job description ---
    job_description = (job_description or "").strip()
    if not job_description:
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    if len(job_description) > settings.max_jd_length:
        raise HTTPException(
            status_code=400,
            detail=f"Job description is too long (max {settings.max_jd_length} characters).",
        )

    # --- Validate resume file ---
    if resume.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=400, detail="Resume must be a PDF file.")

    file_bytes = await _read_upload_bounded(resume, settings.max_pdf_size_bytes)
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded resume file is empty.")

    # --- Bound concurrent analyses (protects CPU and memory) ---
    semaphore = request.app.state.analysis_semaphore
    try:
        await asyncio.wait_for(
            semaphore.acquire(),
            timeout=max(0.001, settings.max_concurrency_wait_seconds),
        )
    except TimeoutError as exc:
        raise _busy_error() from exc

    try:
        resume_text = await run_in_threadpool(extract_text_from_pdf, file_bytes)
        result = await run_analysis(
            resume_text, job_description, request.app.state.embedding_provider
        )
    except EmbeddingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbeddingTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except EmbeddingProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        semaphore.release()

    return AnalyzeResponse(**result)
