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
  * Every attempt has a hard wall-clock deadline (httpx timeouts alone are per-operation,
    so a provider that keeps trickling bytes could otherwise hold a request forever), and
    retries are bounded by both an attempt count and an overall deadline.
  * Provider responses are streamed and capped before they are buffered.
  * Resume/job text, API keys and upstream response bodies are never logged: error
    details carry only a status code or an error class.
"""

import asyncio
import ipaddress
import json
import logging
import math
import random
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from .config import EmbeddingSettings, load_embedding_settings

logger = logging.getLogger("jobfit.embeddings")

_MAX_BACKOFF_SECONDS = 4.0
_MAX_RETRY_AFTER_SECONDS = 120.0
_RETRYABLE_STATUS = {500, 502, 503, 504}
_ERROR_BODY_PEEK_BYTES = 4096  # most we read from a non-200 body (only for HF's "estimated_time")
_MIN_ATTEMPT_SECONDS = 0.25  # do not start an attempt with less budget than this
_MAX_DETAIL_CHARS = 200
_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
_API_KEY_RE = re.compile(r"[\x21-\x7e]{1,512}")  # visible ASCII only: no spaces/control chars


# ---------------------------------------------------------------------------
# Errors. `public_message` is safe to show to end users; `detail` is for logs.
# ---------------------------------------------------------------------------

class EmbeddingError(Exception):
    status_code = 502
    public_message = "Semantic similarity could not be computed right now. Please try again shortly."
    retryable = False

    def __init__(self, detail: str = "", *, retry_after: Optional[float] = None):
        # `detail` is written to logs, so it is bounded and must only ever be built from
        # our own text, status codes and error-class names -- never from upstream bodies.
        detail = detail[:_MAX_DETAIL_CHARS]
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


def _to_unit_vector(vec: Any) -> List[float]:
    """
    Return `vec` scaled to unit length, or raise EmbeddingResponseError.

    The vector is first divided by its largest absolute component, so every component
    is in [-1, 1] and squaring/summing cannot overflow (naively, [1e200] has an infinite
    norm) or underflow to zero (naively, [1e-200] looks like a zero vector).
    """
    try:
        values = [float(x) for x in vec]  # OverflowError for integers beyond float range
    except (OverflowError, TypeError, ValueError):
        raise EmbeddingResponseError("vector contains an unusable value") from None
    if not values:
        raise EmbeddingResponseError("vector is empty")
    if not all(math.isfinite(v) for v in values):
        raise EmbeddingResponseError("vector contains a non-finite value")
    scale = max(abs(v) for v in values)
    if scale == 0.0:
        raise EmbeddingResponseError("vector has zero norm")
    scaled = [v / scale for v in values]
    norm = math.sqrt(math.fsum(v * v for v in scaled))  # in [1, sqrt(len)]
    return [v / norm for v in scaled]


def validate_vectors(raw: Any, expected_count: int) -> List[List[float]]:
    """
    Strictly validate provider output and return unit-length vectors.
    Raises EmbeddingResponseError on anything odd.
    """
    if not isinstance(raw, list) or len(raw) != expected_count:
        raise EmbeddingResponseError(f"expected {expected_count} vectors")

    vectors: List[List[float]] = []
    for vec in raw:
        if not isinstance(vec, list) or not vec:
            raise EmbeddingResponseError("vector is not a non-empty list (token-level output?)")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in vec):
            raise EmbeddingResponseError("vector contains a non-numeric value")
        vectors.append(_to_unit_vector(vec))

    if len({len(v) for v in vectors}) != 1:
        raise EmbeddingResponseError("vectors have different dimensions")
    return vectors


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity in [-1, 1]. Inputs are normalized first, so the result does not
    depend on their scale; a non-finite or undefined result raises instead of being
    passed on (a NaN would otherwise be clamped into a perfect score).
    """
    unit_a, unit_b = _to_unit_vector(a), _to_unit_vector(b)
    if len(unit_a) != len(unit_b):
        raise EmbeddingResponseError("vectors have different dimensions")
    dot = math.fsum(x * y for x, y in zip(unit_a, unit_b))
    if not math.isfinite(dot):
        raise EmbeddingResponseError("similarity is not a finite number")
    return max(-1.0, min(1.0, dot))


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _url_problem(url: str) -> Optional[str]:
    """Why an EMBEDDING_API_URL override is unacceptable, or None. The API key is sent to it."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return "EMBEDDING_API_URL is not a valid URL"
    if parts.scheme not in ("https", "http") or not host:
        return "EMBEDDING_API_URL must be an absolute https:// URL"
    if parts.username is not None or parts.password is not None:
        return "EMBEDDING_API_URL must not contain credentials"
    if parts.scheme == "http" and not _is_loopback_host(host):
        return "EMBEDDING_API_URL must use https:// (plain http is only allowed for localhost)"
    return None


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
        # Never follow redirects: the API key travels in a request header and must not be
        # forwarded to wherever an upstream (or a misconfigured URL) points us next.
        return httpx.AsyncClient(
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=2),
            follow_redirects=False,
        )

    # -- configuration ------------------------------------------------------

    def configuration_problem(self) -> Optional[str]:
        """Return why the client cannot be used, or None when it is ready. No network."""
        # Messages name settings, never their values: they reach the logs and a value
        # could be a credential or a URL containing one.
        cfg = self.settings
        if cfg.provider not in PROVIDERS:
            return f"unknown EMBEDDING_PROVIDER (supported: {', '.join(sorted(PROVIDERS))})"
        if not cfg.api_key:
            return f"no API key set for provider '{cfg.provider}'"
        if not _API_KEY_RE.fullmatch(cfg.api_key):
            return "the embedding API key contains whitespace, control or non-ASCII characters"
        if not cfg.model and not cfg.api_url:
            return "no EMBEDDING_MODEL set"
        if cfg.model and (not _MODEL_ID_RE.fullmatch(cfg.model) or len(cfg.model) > 128):
            return "EMBEDDING_MODEL contains characters that are not valid in a model id"
        if cfg.api_url:
            return _url_problem(cfg.api_url)
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
        # Ask for an uncompressed body so the byte cap below bounds what we really buffer.
        headers = {**headers, "Accept-Encoding": "identity"}

        http = await self._get_http()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + cfg.total_timeout_seconds
        attempts = cfg.max_retries + 1
        last_error: EmbeddingError = EmbeddingTimeout("no attempt was made before the deadline")

        for attempt in range(attempts):
            remaining = deadline - loop.time()
            if remaining < _MIN_ATTEMPT_SECONDS:
                break  # too little time left for a meaningful attempt; report the last real error
            result = await self._attempt(
                http, url, headers, body, parse, len(texts), min(cfg.timeout_seconds, remaining)
            )  # `min(...)` is this attempt's hard wall-clock budget
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

    async def _attempt(self, http, url, headers, body, parse, expected, budget):
        """
        One attempt with a hard wall-clock deadline of `budget` seconds covering connect,
        send, headers AND the whole body. (httpx's own timeouts apply to each network
        operation separately, so on their own they cannot stop a response that keeps
        trickling bytes.) Returns vectors on success, or an EmbeddingError instance.
        """
        try:
            return await asyncio.wait_for(
                self._exchange(http, url, headers, body, parse, expected, budget), timeout=budget
            )
        except asyncio.TimeoutError:
            return EmbeddingTimeout(f"no complete response within {budget:.1f}s")

    async def _exchange(self, http, url, headers, body, parse, expected, budget):
        cap = self.settings.max_response_bytes
        try:
            async with http.stream("POST", url, headers=headers, json=body, timeout=budget) as response:
                status = response.status_code
                if status == 200:
                    raw = await self._read_capped(response, cap)
                    try:
                        return validate_vectors(parse(json.loads(raw)), expected)
                    except (ValueError, RecursionError):  # not JSON / not UTF-8 / absurdly nested
                        return EmbeddingResponseError("response body is not valid JSON")

                # Error responses are not buffered: the status alone decides what we do. The
                # one exception is a small peek at a 503 body for Hugging Face's load estimate.
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                if status in (401, 403):
                    return EmbeddingAuthError(f"HTTP {status}")
                if status == 429:
                    return EmbeddingRateLimited("HTTP 429", retry_after=retry_after)
                if status in _RETRYABLE_STATUS:
                    if status == 503 and retry_after is None:
                        retry_after = await self._estimated_load_time(response)
                    return EmbeddingProviderError(f"HTTP {status}", retryable=True, retry_after=retry_after)
                return EmbeddingProviderError(f"HTTP {status}", retryable=False)
        except EmbeddingError as exc:  # e.g. oversized body from _read_capped
            return exc
        except httpx.TimeoutException:
            return EmbeddingTimeout(f"no response within {budget:.1f}s")
        except httpx.DecodingError:
            return EmbeddingResponseError("response has an invalid content-encoding")
        except httpx.TransportError as exc:
            return EmbeddingProviderError(f"network error: {type(exc).__name__}", retryable=True)
        except httpx.HTTPError as exc:
            return EmbeddingProviderError(f"request error: {type(exc).__name__}", retryable=False)

    @staticmethod
    async def _read_capped(response: httpx.Response, limit: int) -> bytes:
        """Read the decoded body, stopping as soon as it exceeds `limit` bytes."""
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            raise EmbeddingResponseError(f"response larger than {limit} bytes")
        buffer = bytearray()
        async for chunk in response.aiter_bytes():
            buffer += chunk
            if len(buffer) > limit:
                raise EmbeddingResponseError(f"response larger than {limit} bytes")
        return bytes(buffer)

    @staticmethod
    async def _estimated_load_time(response: httpx.Response) -> Optional[float]:
        """Hugging Face's 503 'model is loading' body carries {"estimated_time": seconds}."""
        try:
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer += chunk
                if len(buffer) >= _ERROR_BODY_PEEK_BYTES:
                    return None  # too big to be the tiny JSON we are looking for
            value = json.loads(bytes(buffer)).get("estimated_time")
        except (ValueError, AttributeError, RecursionError, httpx.HTTPError):
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
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
