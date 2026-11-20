"""
main.py
FastAPI application entrypoint for JobFit AI backend.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .analyzer import run_analysis
from .config import MAX_JD_LENGTH, MAX_PDF_SIZE_BYTES, MAX_REQUEST_BODY_BYTES
from .embeddings import EmbeddingError, get_embedding_client, set_embedding_client
from .limits import BodySizeLimitMiddleware, ServerBusy, get_gate, reset_gate
from .pdf_parser import extract_text_from_pdf
from .schemas import AnalyzeResponse

logger = logging.getLogger("jobfit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup does no model loading and no network I/O: the process stays small and
    # boots fast on a 512 MB host. Embeddings are fetched per request from the provider.
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


app = FastAPI(
    title="JobFit AI",
    description="AI/NLP resume-to-job-description match analyzer (ATS-style, not an official ATS).",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware order matters: the last one added is the outermost. The size limiter is added
# first so it sits *inside* CORS, which lets its 413 response carry CORS headers.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

# CORS: allow the configured frontend origin(s). Defaults to "*" for local dev.
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
origins = [o.strip() for o in allowed_origins.split(",")] if allowed_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_supabase_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to analyze a resume.")

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        raise HTTPException(status_code=503, detail="Account authentication is not configured.")

    token = authorization.split(" ", 1)[1].strip()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": publishable_key,
            },
        )

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")

    user_id = response.json().get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unable to verify your account.")
    return user_id


async def reserve_monthly_analysis(
    user_id: str = Depends(require_supabase_user),
    authorization: str | None = Header(default=None),
) -> str:
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not supabase_url or not publishable_key:
        raise HTTPException(status_code=503, detail="Account authentication is not configured.")

    token = (authorization or "").split(" ", 1)[1].strip()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{supabase_url}/rest/v1/rpc/reserve_analysis",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": publishable_key,
                "Content-Type": "application/json",
            },
            json={},
        )

    if response.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail="You have reached this month's analysis limit.",
        )
    if response.status_code >= 400:
        logger.error("usage reservation failed: %s %s", response.status_code, response.text)
        raise HTTPException(status_code=503, detail="Unable to verify your analysis allowance.")

    result = response.json()
    if isinstance(result, dict) and result.get("allowed") is False:
        raise HTTPException(
            status_code=403,
            detail="You have reached this month's analysis limit.",
        )
    return user_id


@app.exception_handler(EmbeddingError)
async def embedding_error_handler(request: Request, exc: EmbeddingError):
    # Same {"detail": ...} shape the frontend already reads. No scores are returned:
    # a failed semantic-similarity step fails the whole analysis.
    logger.error("analysis failed: %s (%s)", type(exc).__name__, exc.detail)
    headers = {}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(max(1, int(round(exc.retry_after))))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.public_message}, headers=headers)


@app.exception_handler(ServerBusy)
async def server_busy_handler(request: Request, exc: ServerBusy):
    return JSONResponse(
        status_code=503,
        content={"detail": "The server is busy analyzing other resumes. Please try again in a few seconds."},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


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
    resume: UploadFile = File(...),
    job_description: str = Form(...),
    user_id: str = Depends(reserve_monthly_analysis),
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

    # --- Extract + analyze, with bounded concurrency ---
    # The upload is read into RAM only once a slot is held, so at most MAX_CONCURRENT_ANALYSES
    # resumes are ever memory-resident no matter how many requests arrive at once.
    async with get_gate():
        file_bytes = await resume.read(MAX_PDF_SIZE_BYTES + 1)  # +1 detects "too big"
        _check_resume_size(len(file_bytes))
        resume_text = await asyncio.to_thread(extract_text_from_pdf, file_bytes)
        del file_bytes  # release the raw upload before the (slower) embedding call
        result = await run_analysis(resume_text, job_description)

    return AnalyzeResponse(**result)


def _check_resume_size(size) -> None:
    if size is None:
        return  # unknown until read; re-checked after reading
    if size == 0:
        raise HTTPException(status_code=400, detail="Uploaded resume file is empty.")
    if size > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume PDF exceeds 5 MB limit.")
