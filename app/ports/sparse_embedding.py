"""Port that turns text into sparse term weights for keyword search."""

import abc
from collections.abc import Sequence

from app.domain import rag


class SparseEmbedding(abc.ABC):
    """Sparse text model loaded once and reused for every call."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Returns the identifier of the loaded model.

        Returns:
            The model name, e.g. ``Qdrant/bm25``.
        """

    @abc.abstractmethod
    def embed_documents(  # noqa: DOC502
        self, texts: Sequence[str]
    ) -> list[rag.SparseVector]:
        """Weights the terms of passages to be stored.

        Args:
            texts: The passages.

        Returns:
            One sparse vector per passage, in order.

        Raises:
            EmbeddingError: If the model fails.
        """

    @abc.abstractmethod
    def embed_query(self, text: str) -> rag.SparseVector:  # noqa: DOC502
        """Weights the terms of a question.

        Args:
            text: The question.

        Returns:
            The question's sparse vector.

        Raises:
            EmbeddingError: If the model fails.
        """
