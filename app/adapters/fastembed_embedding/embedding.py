"""Embedding backed by a FastEmbed ONNX model."""

from collections.abc import Sequence
from typing import Self

import fastembed

from app import config
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
    def load(cls, settings: config.EmbeddingSettings) -> Self:  # noqa: DOC501, DOC503
        """Loads the model from the configured cache directory.

        Args:
            settings: Model name, cache directory and download policy.

        Returns:
            The adapter.
        """
        raise NotImplementedError

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

    def embed_documents(self, texts: Sequence[str]) -> list[rag.Vector]:  # noqa: DOC501, DOC503
        """Embeds passages to be stored.

        Args:
            texts: The passages.

        Returns:
            One vector per passage, in order.
        """
        raise NotImplementedError

    def embed_query(self, text: str) -> rag.Vector:  # noqa: DOC501, DOC503
        """Embeds a question, prefixed with the retrieval instruction.

        Args:
            text: The question.

        Returns:
            The question's vector.
        """
        raise NotImplementedError
