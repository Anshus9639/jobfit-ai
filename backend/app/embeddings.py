"""
embeddings.py
Remote text-embedding client used for the semantic-similarity signal.

Why this exists: running sentence-transformers + PyTorch inside the web process needs
far more than the 512 MB available on Render's free tier. Embeddings are now computed
by an external provider over HTTPS and only the resulting vectors come back.

Design rules:
  * Importing this module and starting the app never touches the network and never
    needs credentials; failures surface per request, as typed errors.
  * A failed or invalid embedding call raises. It is NEVER replaced by a default,
    fallback, or estimated similarity score.
  * Retries are bounded by both an attempt count and an overall deadline.
  * Resume/job text and API keys are never logged.
"""

import asyncio
import logging
import math
import random
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from .config import EmbeddingSettings, load_embedding_settings

logger = logging.getLogger("jobfit.embeddings")

_MAX_BACKOFF_SECONDS = 4.0
_MAX_RETRY_AFTER_SECONDS = 120.0
_RETRYABLE_STATUS = {500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Errors. `public_message` is safe to show to end users; `detail` is for logs.
# ---------------------------------------------------------------------------

class EmbeddingError(Exception):
    status_code = 502
    public_message = "Semantic similarity could not be computed right now. Please try again shortly."
    retryable = False

    def __init__(self, detail: str = "", *, retry_after: Optional[float] = None):
        super().__init__(detail or self.public_message)
        self.detail = detail
        self.retry_after = retry_after


class EmbeddingNotConfigured(EmbeddingError):
    status_code = 503
    public_message = (
        "Semantic similarity is unavailable: the embedding service is not configured on the server."
    )


class EmbeddingAuthError(EmbeddingError):
    status_code = 503
    public_message = (
        "Semantic similarity is unavailable: the server's embedding credentials were rejected."
    )


class EmbeddingTimeout(EmbeddingError):
    status_code = 504
    public_message = "The embedding service timed out. Please try again shortly."
    retryable = True


class EmbeddingRateLimited(EmbeddingError):
    status_code = 503
    public_message = "The embedding service is rate-limiting requests. Please try again shortly."
    retryable = True


class EmbeddingProviderError(EmbeddingError):
    """Upstream 5xx / network failure (retryable) or a rejected request (not retryable)."""

    status_code = 502

    def __init__(self, detail: str = "", *, retryable: bool = False, retry_after: Optional[float] = None):
        super().__init__(detail, retry_after=retry_after)
        self.retryable = retryable


class EmbeddingResponseError(EmbeddingError):
    """The provider answered 200 but the payload was not usable."""

    status_code = 502
    public_message = "The embedding service returned an invalid response."


# ---------------------------------------------------------------------------
# Provider adapters: build the HTTP request and parse the response.
# ---------------------------------------------------------------------------

Request = Tuple[str, Dict[str, str], Dict[str, Any]]  # url, headers, json body


def _huggingface_request(cfg: EmbeddingSettings, texts: List[str]) -> Request:
    url = cfg.api_url or (
        f"https://router.huggingface.co/hf-inference/models/{cfg.model}/pipeline/feature-extraction"
    )
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    return url, headers, {"inputs": texts, "truncate": True}


def _huggingface_parse(data: Any) -> Any:
    # Expected: one pooled vector per input -> [[float, ...], [float, ...]].
    return data


def _gemini_request(cfg: EmbeddingSettings, texts: List[str]) -> Request:
    url = cfg.api_url or (
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.model}:batchEmbedContents"
    )
    headers = {"x-goog-api-key": cfg.api_key or ""}
    body = {
        "requests": [
            {"model": f"models/{cfg.model}", "content": {"parts": [{"text": text}]}}
            for text in texts
        ]
    }
    return url, headers, body


def _gemini_parse(data: Any) -> Any:
    if not isinstance(data, dict) or not isinstance(data.get("embeddings"), list):
        raise EmbeddingResponseError("gemini: missing 'embeddings' list")
    vectors = []
    for item in data["embeddings"]:
        if not isinstance(item, dict) or "values" not in item:
            raise EmbeddingResponseError("gemini: embedding entry without 'values'")
        vectors.append(item["values"])
    return vectors


PROVIDERS: Dict[str, Tuple[Callable[..., Request], Callable[[Any], Any]]] = {
    "huggingface": (_huggingface_request, _huggingface_parse),
    "gemini": (_gemini_request, _gemini_parse),
}


def validate_vectors(raw: Any, expected_count: int) -> List[List[float]]:
    """Strictly validate provider output; raise EmbeddingResponseError on anything odd."""
    if not isinstance(raw, list) or len(raw) != expected_count:
        raise EmbeddingResponseError(f"expected {expected_count} vectors")

    vectors: List[List[float]] = []
    for vec in raw:
        if not isinstance(vec, list) or not vec:
            raise EmbeddingResponseError("vector is not a non-empty list (token-level output?)")
        for x in vec:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
                raise EmbeddingResponseError("vector contains a non-numeric or non-finite value")
        vectors.append([float(x) for x in vec])

    if len({len(v) for v in vectors}) != 1:
        raise EmbeddingResponseError("vectors have different dimensions")
    if any(math.sqrt(sum(x * x for x in v)) == 0.0 for v in vectors):
        raise EmbeddingResponseError("vector has zero norm")
    return vectors


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None  # HTTP-date form is not supported; fall back to our own backoff
    return max(0.0, min(seconds, _MAX_RETRY_AFTER_SECONDS))


class EmbeddingClient:
    def __init__(
        self,
        settings: Optional[EmbeddingSettings] = None,
        http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ):
        self.settings = settings or load_embedding_settings()
        self._factory = http_client_factory or self._default_http_client
        self._http: Optional[httpx.AsyncClient] = None
        self._init_lock = asyncio.Lock()
        self._sleep = asyncio.sleep  # indirection so tests can skip real waiting

    @staticmethod
    def _default_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(limits=httpx.Limits(max_connections=10, max_keepalive_connections=2))

    # -- configuration ------------------------------------------------------

    def configuration_problem(self) -> Optional[str]:
        """Return why the client cannot be used, or None when it is ready. No network."""
        cfg = self.settings
        if cfg.provider not in PROVIDERS:
            return f"unknown EMBEDDING_PROVIDER '{cfg.provider}' (supported: {', '.join(sorted(PROVIDERS))})"
        if not cfg.api_key:
            return f"no API key set for provider '{cfg.provider}'"
        if not cfg.model and not cfg.api_url:
            return "no EMBEDDING_MODEL set"
        return None

    def ensure_configured(self) -> None:
        problem = self.configuration_problem()
        if problem:
            raise EmbeddingNotConfigured(problem)

    # -- lifecycle ----------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        # Double-checked under a lock so concurrent first requests create exactly one client.
        if self._http is None:
            async with self._init_lock:
                if self._http is None:
                    self._http = self._factory()
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- embedding ----------------------------------------------------------

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Return one validated vector per text, or raise an EmbeddingError."""
        self.ensure_configured()
        cfg = self.settings
        build_request, parse = PROVIDERS[cfg.provider]
        url, headers, body = build_request(cfg, [t[: cfg.max_input_chars] for t in texts])

        http = await self._get_http()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + cfg.total_timeout_seconds
        attempts = cfg.max_retries + 1
        last_error: EmbeddingError = EmbeddingTimeout("no attempt was made before the deadline")

        for attempt in range(attempts):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            result = await self._attempt(
                http, url, headers, body, parse, len(texts), min(cfg.timeout_seconds, remaining)
            )
            if not isinstance(result, EmbeddingError):
                return result  # success: validated vectors
            last_error = result

            logger.warning(
                "embedding attempt %d/%d failed (provider=%s, error=%s)",
                attempt + 1, attempts, cfg.provider, type(last_error).__name__,
            )
            if not last_error.retryable or attempt == attempts - 1:
                raise last_error

            delay = last_error.retry_after
            if delay is None:
                delay = min(_MAX_BACKOFF_SECONDS, 0.5 * (2 ** attempt)) * random.uniform(0.5, 1.0)
            if delay >= deadline - loop.time():
                raise last_error  # waiting would blow the overall deadline
            await self._sleep(delay)

        raise last_error

    async def _attempt(self, http, url, headers, body, parse, expected, timeout):
        """One HTTP attempt. Returns vectors on success, or an EmbeddingError instance."""
        try:
            response = await http.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException:
            return EmbeddingTimeout(f"no response within {timeout:.1f}s")
        except httpx.TransportError as exc:
            return EmbeddingProviderError(f"network error: {type(exc).__name__}", retryable=True)

        status = response.status_code
        if status == 200:
            try:
                return validate_vectors(parse(response.json()), expected)
            except EmbeddingError as exc:
                return exc
            except ValueError:
                return EmbeddingResponseError("response body is not valid JSON")

        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        snippet = self._safe_snippet(response)
        if status in (401, 403):
            return EmbeddingAuthError(f"HTTP {status}")
        if status == 429:
            return EmbeddingRateLimited(f"HTTP 429 {snippet}", retry_after=retry_after)
        if status in _RETRYABLE_STATUS:
            if status == 503 and retry_after is None:
                retry_after = self._estimated_load_time(response)  # HF "model is loading"
            return EmbeddingProviderError(f"HTTP {status} {snippet}", retryable=True, retry_after=retry_after)
        return EmbeddingProviderError(f"HTTP {status} {snippet}", retryable=False)

    def _safe_snippet(self, response: httpx.Response) -> str:
        text = response.text[:120].replace("\n", " ")
        key = self.settings.api_key
        return text.replace(key, "***") if key else text

    @staticmethod
    def _estimated_load_time(response: httpx.Response) -> Optional[float]:
        try:
            value = response.json().get("estimated_time")
        except (ValueError, AttributeError):
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(float(value), _MAX_RETRY_AFTER_SECONDS))
        return None


# ---------------------------------------------------------------------------
# Process-wide singleton (construction is cheap and does no I/O).
# ---------------------------------------------------------------------------

_client: Optional[EmbeddingClient] = None
_client_lock = threading.Lock()


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = EmbeddingClient()
    return _client


def set_embedding_client(client: Optional[EmbeddingClient]) -> None:
    """Replace (or with None, reset) the singleton. Used by tests and shutdown."""
    global _client
    with _client_lock:
        _client = client
