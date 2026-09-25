"""Embedding backed by a FastEmbed ONNX model."""

from collections.abc import Sequence
from typing import Self

import fastembed

from app import config
from app.domain import errors
from app.domain import rag
from app.ports import embedding


class FastEmbedEmbedding(embedding.Embedding):
    """Embeds passages as stored and questions with the model's prefix."""

    def __init__(
        self,
        model: fastembed.TextEmbedding,
        model_name: str,
        dimension: int,
        query_prefix: str,
    ) -> None:
        """Initializes the adapter.

        Args:
            model: The loaded FastEmbed model.
            model_name: Its identifier.
            dimension: Length of the vectors it produces.
            query_prefix: Instruction prepended to questions only.
        """
        self._model = model
        self._model_name = model_name
        self._dimension = dimension
        self._query_prefix = query_prefix

    @classmethod
    def load(cls, settings: config.EmbeddingSettings) -> Self:
        """Loads the model from the configured cache directory.

        Args:
            settings: Model name, cache directory and download policy.

        Returns:
            The adapter.

        Raises:
            errors.EmbeddingError: If the model cannot be loaded, e.g. it is
                missing and downloads are forbidden.
        """
        try:
            model = fastembed.TextEmbedding(
                settings.model_name,
                cache_dir=str(settings.cache_dir),
                local_files_only=settings.local_files_only,
            )
        except ValueError as exc:
            raise errors.EmbeddingError(
                f"Embedding model {settings.model_name!r} is not available in "
                "DOCINTEL_EMBEDDINGS__CACHE_DIR."
            ) from exc
        return cls(
            model,
            settings.model_name,
            fastembed.TextEmbedding.get_embedding_size(settings.model_name),
            settings.query_prefix,
        )

    @property
    def model_name(self) -> str:
        """Returns the identifier of the loaded model.

        Returns:
            The model name.
        """
        return self._model_name

    @property
    def dimension(self) -> int:
        """Returns the length of the vectors the model produces.

        Returns:
            The vector dimension.
        """
        return self._dimension

    def embed_documents(self, texts: Sequence[str]) -> list[rag.Vector]:
        """Embeds passages to be stored.

        Args:
            texts: The passages.

        Returns:
            One vector per passage, in order.
        """
        return [
            tuple(float(value) for value in vector)
            for vector in self._model.passage_embed(list(texts))
        ]

    def embed_query(self, text: str) -> rag.Vector:
        """Embeds a question, prefixed with the retrieval instruction.

        Args:
            text: The question.

        Returns:
            The question's vector.
        """
        vector = next(iter(self._model.query_embed(self._query_prefix + text)))
        return tuple(float(value) for value in vector)
