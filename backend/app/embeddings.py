"""
embeddings.py
Pluggable text-embedding backends.

Default deployment uses a hosted embedding API so the web process does not
import PyTorch or hold model weights in memory. A local SentenceTransformer
backend remains available for development via requirements-local.txt.

Failure semantics are explicit: providers raise EmbeddingError subclasses and
callers must surface an error. No provider ever fabricates an embedding or a
similarity score.
"""

import asyncio
import importlib.util
import math
import threading
from typing import Any, List, Optional, Sequence

import httpx

from .config import Settings

RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class EmbeddingError(Exception):
    """Base class for semantic-similarity backend failures."""


class EmbeddingNotConfigured(EmbeddingError):
    """No usable credentials/dependencies are configured."""


class EmbeddingTimeout(EmbeddingError):
    """The provider did not answer within the configured budget."""


class EmbeddingProviderError(EmbeddingError):
    """The provider returned an error or an unusable response."""


def _validate_vectors(vectors: Any, expected_count: int, provider_name: str) -> List[List[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise EmbeddingProviderError(
            f"{provider_name} returned {len(vectors) if isinstance(vectors, list) else 'no'} "
            f"embedding(s) for {expected_count} input(s)."
        )

    normalized: List[List[float]] = []
    dimension: Optional[int] = None

    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingProviderError(f"{provider_name} returned an empty or malformed embedding.")
        if dimension is None:
            dimension = len(vector)
        elif len(vector) != dimension:
            raise EmbeddingProviderError(
                f"{provider_name} returned embeddings with inconsistent dimensions."
            )
        try:
            floats = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise EmbeddingProviderError(
                f"{provider_name} returned a non-numeric embedding."
            ) from exc
        if not all(math.isfinite(value) for value in floats):
            raise EmbeddingProviderError(f"{provider_name} returned non-finite embedding values.")
        normalized.append(floats)

    return normalized


def _mean_pool(token_embeddings: Any, provider_name: str) -> List[float]:
    if not isinstance(token_embeddings, list) or not token_embeddings:
        raise EmbeddingProviderError(f"{provider_name} returned malformed token embeddings.")
    token_vectors = _validate_vectors(token_embeddings, len(token_embeddings), provider_name)
    width = len(token_vectors[0])
    return [math.fsum(vector[i] for vector in token_vectors) / len(token_vectors) for i in range(width)]


class EmbeddingProvider:
    name = "base"

    @property
    def is_configured(self) -> bool:
        return True

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class _HttpEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key: Optional[str],
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        backoff_seconds: float,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._client = client or httpx.AsyncClient(trust_env=False)
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _request_url(self) -> str:
        raise NotImplementedError

    def _request_payload(self, texts: Sequence[str]) -> dict:
        raise NotImplementedError

    def _parse_response(self, payload: Any, expected_count: int) -> List[List[float]]:
        raise NotImplementedError

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not self._api_key:
            raise EmbeddingNotConfigured(
                "Semantic similarity is not configured on the server. "
                "Set EMBEDDINGS_API_KEY (and optionally EMBEDDINGS_PROVIDER) in the environment."
            )
        if not texts:
            return []

        payload = self._request_payload(texts)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        attempts = self._max_retries + 1
        last_error: Optional[EmbeddingError] = None

        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    self._request_url(),
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = EmbeddingTimeout(
                    f"The embedding provider timed out after {self._timeout:g}s "
                    f"(attempt {attempt + 1}/{attempts}). Please retry."
                )
                cause: Optional[BaseException] = exc
            except httpx.HTTPError as exc:
                last_error = EmbeddingProviderError(
                    f"Could not reach the embedding provider "
                    f"(attempt {attempt + 1}/{attempts}). Please retry."
                )
                cause = exc
            else:
                if response.status_code == 200:
                    try:
                        body = response.json()
                    except ValueError as exc:
                        raise EmbeddingProviderError(
                            "The embedding provider returned a non-JSON response."
                        ) from exc
                    return self._parse_response(body, len(texts))

                if response.status_code in (401, 403):
                    raise EmbeddingProviderError(
                        f"The embedding provider rejected the API credentials "
                        f"(HTTP {response.status_code}). Check EMBEDDINGS_API_KEY."
                    )

                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < attempts - 1
                ):
                    last_error = EmbeddingProviderError(
                        f"The embedding provider is unavailable (HTTP {response.status_code}). "
                        f"Please retry."
                    )
                    cause = None
                else:
                    raise EmbeddingProviderError(
                        f"The embedding provider request failed with HTTP {response.status_code}"
                        + (f" after {attempts} attempts." if response.status_code in RETRYABLE_STATUS_CODES else ".")
                    )

            if attempt < attempts - 1 and self._backoff > 0:
                await asyncio.sleep(self._backoff * (2**attempt))

        assert last_error is not None
        raise last_error from cause

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class HuggingFaceEmbeddingProvider(_HttpEmbeddingProvider):
    """
    Hugging Face Inference Providers feature-extraction endpoint.

    Default URL shape:
    https://router.huggingface.co/hf-inference/models/<model>/pipeline/feature-extraction
    """

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        super().__init__(
            name="huggingface",
            api_key=settings.embeddings_api_key,
            base_url=settings.embeddings_base_url,
            model=settings.embeddings_model,
            timeout_seconds=settings.embeddings_timeout_seconds,
            max_retries=settings.embeddings_max_retries,
            backoff_seconds=settings.embeddings_retry_backoff_seconds,
            client=client,
        )

    def _request_url(self) -> str:
        return f"{self._base_url}/models/{self._model}/pipeline/feature-extraction"

    def _request_payload(self, texts: Sequence[str]) -> dict:
        return {"inputs": list(texts), "options": {"wait_for_model": True}, "truncate": True}

    def _parse_response(self, payload: Any, expected_count: int) -> List[List[float]]:
        if isinstance(payload, dict):
            if "error" in payload:
                raise EmbeddingProviderError(
                    "The Hugging Face inference API reported an error for this request."
                )
            raise EmbeddingProviderError("The Hugging Face inference API returned an unexpected payload.")

        if not isinstance(payload, list) or not payload:
            raise EmbeddingProviderError("The Hugging Face inference API returned an empty payload.")

        first = payload[0]
        if isinstance(first, (int, float)):
            vectors = [payload]
        elif isinstance(first, list) and first and isinstance(first[0], (int, float)):
            vectors = payload
        elif isinstance(first, list) and first and isinstance(first[0], list):
            vectors = [_mean_pool(tokens, self.name) for tokens in payload]
        else:
            raise EmbeddingProviderError("The Hugging Face inference API returned an unsupported format.")

        return _validate_vectors(vectors, expected_count, self.name)


class OpenAICompatibleEmbeddingProvider(_HttpEmbeddingProvider):
    """Any OpenAI-compatible /embeddings endpoint (OpenAI, Gemini compat, TEI, ...)."""

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        super().__init__(
            name="openai-compatible",
            api_key=settings.embeddings_api_key,
            base_url=settings.embeddings_base_url,
            model=settings.embeddings_model,
            timeout_seconds=settings.embeddings_timeout_seconds,
            max_retries=settings.embeddings_max_retries,
            backoff_seconds=settings.embeddings_retry_backoff_seconds,
            client=client,
        )

    def _request_url(self) -> str:
        return f"{self._base_url}/embeddings"

    def _request_payload(self, texts: Sequence[str]) -> dict:
        return {"model": self._model, "input": list(texts), "encoding_format": "float"}

    def _parse_response(self, payload: Any, expected_count: int) -> List[List[float]]:
        if not isinstance(payload, dict):
            raise EmbeddingProviderError("The embedding provider returned an unexpected payload.")

        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingProviderError(
                f"The embedding provider returned "
                f"{len(data) if isinstance(data, list) else 'no'} embedding(s) "
                f"for {expected_count} input(s)."
            )

        try:
            ordered = sorted(data, key=lambda item: item.get("index", 0))
        except (AttributeError, TypeError) as exc:
            raise EmbeddingProviderError("The embedding provider returned malformed embedding entries.") from exc

        vectors = []
        for item in ordered:
            if not isinstance(item, dict) or "embedding" not in item:
                raise EmbeddingProviderError("The embedding provider returned a malformed embedding entry.")
            vectors.append(item["embedding"])

        return _validate_vectors(vectors, expected_count, self.name)


_local_model = None
_local_model_lock = threading.Lock()


def _get_local_model(model_name: str):
    """
    Lazily initialize the optional SentenceTransformer exactly once.

    The double-checked lock prevents concurrent first requests from each
    allocating a separate copy of the model (a fast path to OOM).
    """
    global _local_model
    if _local_model is not None:
        return _local_model

    with _local_model_lock:
        if _local_model is not None:
            return _local_model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingNotConfigured(
                "The local embedding provider requires optional dependencies. "
                "Install them with: pip install -r requirements-local.txt"
            ) from exc
        try:
            _local_model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingProviderError(
                f"Could not load the local embedding model '{model_name}'."
            ) from exc
    return _local_model


class LocalSentenceTransformerProvider(EmbeddingProvider):
    """Development-only local inference. Loads PyTorch into the process."""

    name = "local"

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    @property
    def is_configured(self) -> bool:
        try:
            return importlib.util.find_spec("sentence_transformers") is not None
        except (ImportError, ValueError):
            return False

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []

        model = await asyncio.to_thread(_get_local_model, self._model_name)
        vectors = await asyncio.to_thread(
            lambda: model.encode(list(texts), normalize_embeddings=True).tolist()
        )
        return _validate_vectors(vectors, len(texts), self.name)


def build_embedding_provider(
    settings: Settings, client: Optional[httpx.AsyncClient] = None
) -> EmbeddingProvider:
    if settings.embeddings_provider == "local":
        return LocalSentenceTransformerProvider(settings.embeddings_model)
    if settings.embeddings_provider == "openai":
        return OpenAICompatibleEmbeddingProvider(settings, client=client)
    return HuggingFaceEmbeddingProvider(settings, client=client)
