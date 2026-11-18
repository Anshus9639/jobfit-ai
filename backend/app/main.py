"""
main.py
FastAPI application entrypoint for JobFit AI backend.
"""

import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .analyzer import run_analysis
from .config import MAX_JD_LENGTH, MAX_PDF_SIZE_BYTES, MAX_REQUEST_BODY_BYTES, load_rate_limit_settings, validate_settings
from .embeddings import EmbeddingError, get_embedding_client, set_embedding_client
from .limits import AdmissionControlMiddleware, BodySizeLimitMiddleware, reset_gate
from .pdf_parser import extract_text_from_pdf
from .ratelimit import RateLimitExceeded, client_key, get_rate_limiter, reset_rate_limiter
from .schemas import AnalyzeResponse

logger = logging.getLogger("jobfit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup does no model loading and no network I/O: the process stays small and
    # boots fast on a 512 MB host. Embeddings are fetched per request from the provider.
    # Malformed numeric settings stop the deploy here (ConfigError names the variable only).
    validate_settings()
    client = get_embedding_client()
    problem = client.configuration_problem()
    if problem:
        logger.warning(
            "Embedding service is NOT configured (%s). The API will start, but /api/analyze "
            "will return 503 until it is configured.",
            problem,
        )
    else:
        logger.info("Embedding provider: %s (model: %s)", client.settings.provider, client.settings.model)
    yield
    await client.aclose()
    set_embedding_client(None)
    reset_gate()
    reset_rate_limiter()


app = FastAPI(
    title="JobFit AI",
    description="AI/NLP resume-to-job-description match analyzer (ATS-style, not an official ATS).",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware order matters: the last one added is the outermost. Admission control and the
# size limiter sit *inside* CORS so their 503/413 responses carry CORS headers. Admission is
# outside the size limiter: a slot is taken before any of the body is read.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
app.add_middleware(AdmissionControlMiddleware, path="/api/analyze")

# CORS: allow the configured frontend origin(s). Defaults to "*" for local dev.
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
origins = [o.strip() for o in allowed_origins.split(",")] if allowed_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,  # no cookies/auth used; avoids invalid combo with wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(EmbeddingError)
async def embedding_error_handler(request: Request, exc: EmbeddingError):
    # Same {"detail": ...} shape the frontend already reads. No scores are returned:
    # a failed semantic-similarity step fails the whole analysis.
    logger.error("analysis failed: %s (%s)", type(exc).__name__, exc.detail)  # detail: status codes only
    headers = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(max(1, int(round(exc.retry_after))))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.public_message}, headers=headers)


@app.get("/")
def root():
    return {"status": "ok", "service": "JobFit AI backend"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/health/ready")
def health_ready():
    """Reports whether the embedding service is configured. Makes no network call."""
    client = get_embedding_client()
    configured = client.configuration_problem() is None
    return {
        "status": "ready" if configured else "degraded",
        "embedding_provider": client.settings.provider,
        "embedding_configured": configured,
    }


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
    if len(job_description) > MAX_JD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Job description is too long (max {MAX_JD_LENGTH} characters).",
        )

    # --- Validate resume file ---
    if resume.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=400, detail="Resume must be a PDF file.")

    # Starlette has already spooled the upload to a temp file (disk, not RAM), and knows its
    # size, so reject empty/oversized files without pulling any bytes into memory.
    _check_resume_size(resume.size)

    # Fail fast (503) if embeddings aren't configured, before doing any PDF work.
    get_embedding_client().ensure_configured()

    # --- Extract + analyze ---
    # Concurrency was already bounded by AdmissionControlMiddleware, which holds a slot for
    # this whole request (including multipart parsing). Only unexpected failures are caught
    # here, and they are logged by class and code location only -- never message text, which
    # could contain resume or job-description content.
    try:
        file_bytes = await resume.read(MAX_PDF_SIZE_BYTES + 1)  # +1 detects "too big"
        _check_resume_size(len(file_bytes))
        resume_text = await asyncio.to_thread(extract_text_from_pdf, file_bytes)
        del file_bytes  # release the raw upload before the (slower) embedding call

        # Spend provider quota only now that a provider call is imminent.
        _consume_rate_limit(request)
        result = await run_analysis(resume_text, job_description)
    except (HTTPException, EmbeddingError):
        raise
    except Exception as exc:
        frames = "".join(traceback.format_tb(exc.__traceback__))
        logger.error("unexpected error in analysis: %s\n%s", type(exc).__name__, frames)
        raise HTTPException(status_code=500, detail="Analysis failed unexpectedly. Please try again.") from None

    return AnalyzeResponse(**result)


def _consume_rate_limit(request: Request) -> None:
    settings = load_rate_limit_settings()
    key = client_key(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
        settings.trusted_proxy_count,
    )
    try:
        get_rate_limiter().check(key)
    except RateLimitExceeded as exc:
        retry = {"Retry-After": str(int(round(exc.retry_after)))}
        if exc.scope == "client":
            raise HTTPException(
                status_code=429,
                detail="You have reached the analysis limit. Please try again later.",
                headers=retry,
            ) from None
        raise HTTPException(
            status_code=503,
            detail="The service has reached its analysis quota for now. Please try again later.",
            headers=retry,
        ) from None


def _check_resume_size(size) -> None:
    if size is None:
        return  # unknown until read; re-checked after reading
    if size == 0:
        raise HTTPException(status_code=400, detail="Uploaded resume file is empty.")
    if size > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume PDF exceeds 5 MB limit.")
