"""
config.py
Runtime settings, read from environment variables.

Values are read when the `load_*` functions are called (not at import time) so the app
starts cleanly with no configuration, and so tests can change the environment.
Secrets (API keys) are only ever read from the environment -- never hardcoded.

Validation policy: an unset or blank variable uses its default; a variable that is set
but malformed, non-finite or out of range raises `ConfigError` naming the variable (never
its value, which might be a secret pasted into the wrong field). `validate_settings()` is
called at startup so a bad value stops the deploy with a clear message instead of being
silently replaced by a default.
"""

import math
import os
from dataclasses import dataclass
from typing import Optional

# --- Request / upload limits (not environment-tunable: part of the API contract) ---
MAX_PDF_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_JD_LENGTH = 20000  # characters
# Headroom for multipart framing + the job description field (UTF-8, up to 4 bytes/char).
MAX_REQUEST_BODY_BYTES = MAX_PDF_SIZE_BYTES + (MAX_JD_LENGTH * 4) + 64 * 1024

# Upper bound on tracked client keys in the rate limiter (memory bound, not tunable).
MAX_TRACKED_CLIENTS = 10_000


class ConfigError(ValueError):
    """An environment variable is set to an unusable value."""


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        value = None
    if value is None or not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be a whole number between {minimum} and {maximum}.")
    return value


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        value = None
    if value is None or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be a finite number between {minimum:g} and {maximum:g}.")
    return value


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    api_key: Optional[str]
    model: str
    api_url: Optional[str]  # optional override of the provider's default endpoint
    timeout_seconds: float  # wall-clock limit for a single attempt
    total_timeout_seconds: float  # overall deadline across all attempts
    max_retries: int  # retries after the first attempt
    max_input_chars: int  # each text is cut to this length before it leaves the server
    max_response_bytes: int = 1024 * 1024  # decoded bytes accepted from the provider


# Model defaults per provider. `huggingface` serves the same all-MiniLM-L6-v2 model the
# app used locally, so semantic scores stay comparable; other providers use different
# embedding spaces and will produce a different score distribution.
DEFAULT_MODELS = {
    "huggingface": "sentence-transformers/all-MiniLM-L6-v2",
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
        timeout_seconds=_float_env("EMBEDDING_TIMEOUT_SECONDS", 10.0, 1.0, 120.0),
        total_timeout_seconds=_float_env("EMBEDDING_TOTAL_TIMEOUT_SECONDS", 25.0, 1.0, 300.0),
        max_retries=_int_env("EMBEDDING_MAX_RETRIES", 2, 0, 5),
        max_input_chars=_int_env("EMBEDDING_MAX_INPUT_CHARS", 6000, 500, 50_000),
        max_response_bytes=_int_env("EMBEDDING_MAX_RESPONSE_BYTES", 1024 * 1024, 4096, 16 * 1024 * 1024),
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
        max_concurrent=_int_env("MAX_CONCURRENT_ANALYSES", 2, 1, 16),
        max_waiting=_int_env("MAX_WAITING_ANALYSES", 4, 0, 200),
        wait_timeout_seconds=_float_env("ANALYSIS_WAIT_TIMEOUT_SECONDS", 20.0, 1.0, 120.0),
        max_pdf_pages=_int_env("MAX_PDF_PAGES", 15, 1, 100),
        max_resume_chars=_int_env("MAX_RESUME_CHARS", 150_000, 1000, 2_000_000),
    )


@dataclass(frozen=True)
class RateLimitSettings:
    per_client: int  # analyses one client may start per window (0 = unlimited)
    global_limit: int  # analyses the whole service may start per window (0 = unlimited)
    window_seconds: float
    trusted_proxy_count: int  # reverse proxies in front of the app that append to X-Forwarded-For


def load_rate_limit_settings() -> RateLimitSettings:
    return RateLimitSettings(
        per_client=_int_env("RATE_LIMIT_PER_CLIENT", 10, 0, 10_000),
        global_limit=_int_env("RATE_LIMIT_GLOBAL", 100, 0, 100_000),
        window_seconds=_float_env("RATE_LIMIT_WINDOW_SECONDS", 600.0, 10.0, 86_400.0),
        trusted_proxy_count=_int_env("TRUSTED_PROXY_COUNT", 1, 0, 5),
    )


def validate_settings() -> None:
    """Load every settings group once; raises ConfigError on the first bad value."""
    load_embedding_settings()
    load_analysis_limits()
    load_rate_limit_settings()
