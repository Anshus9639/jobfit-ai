"""
config.py
Runtime settings, read from environment variables.

Values are read when `load_settings()` is called (not at import time) so the app
starts cleanly with no configuration, and so tests can change the environment.
Secrets (API keys) are only ever read from the environment — never hardcoded.
"""

import os
from dataclasses import dataclass
from typing import Optional

# --- Request / upload limits (not environment-tunable: part of the API contract) ---
MAX_PDF_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_JD_LENGTH = 20000  # characters
# Headroom for multipart framing + the job description field (UTF-8, up to 4 bytes/char).
MAX_REQUEST_BODY_BYTES = MAX_PDF_SIZE_BYTES + (MAX_JD_LENGTH * 4) + 64 * 1024


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    api_key: Optional[str]
    model: str
    api_url: Optional[str]  # optional override of the provider's default endpoint
    timeout_seconds: float  # per-attempt timeout
    total_timeout_seconds: float  # overall deadline across all attempts
    max_retries: int  # retries after the first attempt
    max_input_chars: int  # each text is cut to this length before it leaves the server


# Model defaults per provider. hf-inference exposes all-MiniLM-L6-v2 only under the
# sentence-similarity task, so its feature-extraction endpoint 404s; bge-small-en-v1.5
# is a live 384-dim replacement. Other providers use different embedding spaces and will
# produce a different score distribution.
DEFAULT_MODELS = {
    "huggingface": "BAAI/bge-small-en-v1.5",
    "gemini": "gemini-embedding-2",
}

# Environment variables each provider reads its API key from (first non-empty wins).
API_KEY_ENV_VARS = {
    "huggingface": ("HF_TOKEN", "HUGGINGFACE_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def load_embedding_settings() -> EmbeddingSettings:
    provider = os.getenv("EMBEDDING_PROVIDER", "huggingface").strip().lower()

    api_key: Optional[str] = os.getenv("EMBEDDING_API_KEY", "").strip() or None
    if api_key is None:
        for var in API_KEY_ENV_VARS.get(provider, ()):
            value = os.getenv(var, "").strip()
            if value:
                api_key = value
                break

    model = os.getenv("EMBEDDING_MODEL", "").strip() or DEFAULT_MODELS.get(provider, "")
    return EmbeddingSettings(
        provider=provider,
        api_key=api_key,
        model=model,
        api_url=os.getenv("EMBEDDING_API_URL", "").strip() or None,
        timeout_seconds=_float_env("EMBEDDING_TIMEOUT_SECONDS", 10.0, minimum=1.0),
        total_timeout_seconds=_float_env("EMBEDDING_TOTAL_TIMEOUT_SECONDS", 25.0, minimum=1.0),
        max_retries=_int_env("EMBEDDING_MAX_RETRIES", 2),
        max_input_chars=_int_env("EMBEDDING_MAX_INPUT_CHARS", 6000, minimum=500),
    )


@dataclass(frozen=True)
class AnalysisLimits:
    max_concurrent: int  # analyses running at once
    max_waiting: int  # analyses allowed to queue behind them
    wait_timeout_seconds: float  # longest a queued analysis waits for a slot
    max_pdf_pages: int
    max_resume_chars: int


def load_analysis_limits() -> AnalysisLimits:
    return AnalysisLimits(
        max_concurrent=_int_env("MAX_CONCURRENT_ANALYSES", 2, minimum=1),
        max_waiting=_int_env("MAX_WAITING_ANALYSES", 4),
        wait_timeout_seconds=_float_env("ANALYSIS_WAIT_TIMEOUT_SECONDS", 20.0, minimum=1.0),
        max_pdf_pages=_int_env("MAX_PDF_PAGES", 15, minimum=1),
        max_resume_chars=_int_env("MAX_RESUME_CHARS", 150_000, minimum=1000),
    )
