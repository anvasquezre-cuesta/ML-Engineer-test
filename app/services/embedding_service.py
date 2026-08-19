"""LangChain-backed OpenAI embeddings behind an application-owned boundary."""

import logging
from collections.abc import Sequence
from math import isfinite
from typing import Protocol

from langchain_openai import OpenAIEmbeddings

from app.config import Settings
from app.services.errors import (
    EmbeddingDependencyError,
    EmbeddingResponseError,
)

logger = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    """Small provider surface used by the application adapter."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LangChainOpenAIEmbeddingService:
    """Generate validated OpenAI vectors without leaking LangChain upstream."""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self._model_name = settings.embedding_model_name
        self._dimensions = settings.embedding_dimensions

        if provider is None:
            if settings.openai_api_key is None:
                raise EmbeddingDependencyError("OPENAI_API_KEY is not configured")

            provider = OpenAIEmbeddings(
                model=settings.embedding_model_name,
                dimensions=settings.embedding_dimensions,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                chunk_size=settings.embedding_batch_size,
                timeout=settings.embedding_timeout_seconds,
                max_retries=settings.embedding_max_retries,
            )

        self._provider = provider

    @property
    def provider(self) -> EmbeddingProvider:
        """Expose the shared LangChain provider to the vector-store adapter."""

        return self._provider

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        """Embed contextualized chunks in provider-managed batches."""

        inputs = list(texts)
        if not inputs:
            return ()
        if any(not text.strip() for text in inputs):
            raise ValueError("embedding input cannot be blank")

        try:
            vectors = self._provider.embed_documents(inputs)
        except Exception as exc:
            logger.exception(
                "Document embedding request failed: model=%s, chunks=%s",
                self._model_name,
                len(inputs),
            )
            raise EmbeddingDependencyError("document embedding request failed") from exc

        return self._validate_vectors(vectors, expected_count=len(inputs))

    def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed one retrieval query with the same model as the documents."""

        if not text.strip():
            raise ValueError("embedding query cannot be blank")

        try:
            vector = self._provider.embed_query(text)
        except Exception as exc:
            logger.exception(
                "Query embedding request failed: model=%s",
                self._model_name,
            )
            raise EmbeddingDependencyError("query embedding request failed") from exc

        return self._validate_vectors((vector,), expected_count=1)[0]

    def _validate_vectors(
        self,
        vectors: Sequence[Sequence[float]],
        *,
        expected_count: int,
    ) -> tuple[tuple[float, ...], ...]:
        """Ensure vectors can be stored safely in the configured pgvector shape."""

        if len(vectors) != expected_count:
            raise EmbeddingResponseError(
                "embedding provider returned an unexpected number of vectors"
            )

        validated: list[tuple[float, ...]] = []
        for vector in vectors:
            try:
                values = tuple(float(value) for value in vector)
            except (TypeError, ValueError) as exc:
                raise EmbeddingResponseError(
                    "embedding provider returned non-numeric values"
                ) from exc

            if len(values) != self._dimensions:
                raise EmbeddingResponseError(
                    "embedding provider returned an unexpected vector dimension"
                )
            if not all(isfinite(value) for value in values):
                raise EmbeddingResponseError(
                    "embedding provider returned non-finite values"
                )
            validated.append(values)

        return tuple(validated)
