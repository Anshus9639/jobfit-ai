"""
main.py
FastAPI application entrypoint for JobFit AI backend.
"""

import os

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import run_analysis, get_model
from .pdf_parser import extract_text_from_pdf
from .schemas import AnalyzeResponse

app = FastAPI(
    title="JobFit AI",
    description="AI/NLP resume-to-job-description match analyzer (ATS-style, not an official ATS).",
    version="1.0.0",
)

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

MAX_PDF_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_JD_LENGTH = 20000  # characters


@app.on_event("startup")
def load_model_on_startup():
    """Warm up the sentence-transformer model once at startup, not per-request."""
    get_model()


@app.get("/")
def root():
    return {"status": "ok", "service": "JobFit AI backend"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(
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

    file_bytes = await resume.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded resume file is empty.")
    if len(file_bytes) > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Resume PDF exceeds 5 MB limit.")

    # --- Extract + analyze ---
    resume_text = extract_text_from_pdf(file_bytes)
    result = run_analysis(resume_text, job_description)

    return AnalyzeResponse(**result)