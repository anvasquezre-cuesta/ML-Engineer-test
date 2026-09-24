"""Port that turns text into dense vectors."""

import abc
from collections.abc import Sequence

from app.domain import rag


class Embedding(abc.ABC):
    """Text embedding model loaded once and reused for every call."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Returns the identifier of the loaded model.

        Returns:
            The model name, e.g. ``BAAI/bge-small-en-v1.5``.
        """

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Returns the length of the vectors the model produces.

        Returns:
            The vector dimension.
        """

    @abc.abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[rag.Vector]:  # noqa: DOC502
        """Embeds passages to be stored.

        Args:
            texts: The passages.

        Returns:
            One vector per passage, in order.

        Raises:
            EmbeddingError: If the model fails.
        """

    @abc.abstractmethod
    def embed_query(self, text: str) -> rag.Vector:  # noqa: DOC502
        """Embeds a question used to search the stored passages.

        Args:
            text: The question.

        Returns:
            The question's vector.

        Raises:
            EmbeddingError: If the model fails.
        """
