"""
config.py
Environment-driven settings for the backend.

Secrets are read from the environment only; nothing here is ever logged or
serialized into API responses.
"""

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_HF_BASE_URL = "https://router.huggingface.co/hf-inference"
DEFAULT_HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"

SUPPORTED_PROVIDERS = ("huggingface", "openai", "local")


def _int_env(name: str, default: int, minimum: int, maximum: Optional[int] = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _float_env(name: str, default: float, minimum: float, maximum: Optional[float] = None) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


@dataclass
class Settings:
    allowed_origins: str
    max_pdf_size_bytes: int
    max_jd_length: int
    max_pdf_pages: int
    max_resume_text_chars: int
    max_embedding_input_chars: int
    max_concurrent_analyses: int
    max_concurrency_wait_seconds: float
    embeddings_provider: str
    embeddings_api_key: Optional[str]
    embeddings_base_url: str
    embeddings_model: str
    embeddings_timeout_seconds: float
    embeddings_max_retries: int
    embeddings_retry_backoff_seconds: float

    @property
    def embeddings_configured(self) -> bool:
        if self.embeddings_provider == "local":
            return True
        return bool(self.embeddings_api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("EMBEDDINGS_PROVIDER", "huggingface").strip().lower()
        if provider not in SUPPORTED_PROVIDERS:
            provider = "huggingface"

        if provider == "huggingface":
            api_key = _first_env("EMBEDDINGS_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY")
            base_url = os.getenv("EMBEDDINGS_BASE_URL", "").strip() or DEFAULT_HF_BASE_URL
            model = os.getenv("EMBEDDINGS_MODEL", "").strip() or DEFAULT_HF_MODEL
        elif provider == "openai":
            api_key = _first_env("EMBEDDINGS_API_KEY", "OPENAI_API_KEY")
            base_url = os.getenv("EMBEDDINGS_BASE_URL", "").strip() or DEFAULT_OPENAI_BASE_URL
            model = os.getenv("EMBEDDINGS_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
        else:  # local (opt-in; requires requirements-local.txt)
            api_key = None
            base_url = ""
            model = os.getenv("EMBEDDINGS_MODEL", "").strip() or DEFAULT_LOCAL_MODEL

        return cls(
            allowed_origins=os.getenv("ALLOWED_ORIGINS", "*"),
            max_pdf_size_bytes=_int_env("MAX_PDF_SIZE_BYTES", 5 * 1024 * 1024, 1),
            max_jd_length=_int_env("MAX_JD_LENGTH", 20000, 1),
            max_pdf_pages=_int_env("MAX_PDF_PAGES", 20, 1),
            max_resume_text_chars=_int_env("MAX_RESUME_TEXT_CHARS", 200_000, 1),
            # Bounds what is sent to the embedding model. Sentence-transformer
            # models truncate at a few hundred tokens anyway; this only avoids
            # oversized provider payloads for very long resumes/JDs.
            max_embedding_input_chars=_int_env("MAX_EMBEDDING_INPUT_CHARS", 8000, 100),
            max_concurrent_analyses=_int_env("MAX_CONCURRENT_ANALYSES", 2, 1, 8),
            max_concurrency_wait_seconds=_float_env("MAX_CONCURRENCY_WAIT_SECONDS", 15.0, 0.0),
            embeddings_provider=provider,
            embeddings_api_key=api_key,
            embeddings_base_url=base_url,
            embeddings_model=model,
            embeddings_timeout_seconds=_float_env("EMBEDDINGS_TIMEOUT_SECONDS", 10.0, 1.0, 60.0),
            embeddings_max_retries=_int_env("EMBEDDINGS_MAX_RETRIES", 2, 0, 5),
            embeddings_retry_backoff_seconds=_float_env(
                "EMBEDDINGS_RETRY_BACKOFF_SECONDS", 0.5, 0.0, 10.0
            ),
        )


settings = Settings.from_env()
