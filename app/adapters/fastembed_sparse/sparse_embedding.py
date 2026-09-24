"""SparseEmbedding backed by a FastEmbed sparse model such as BM25."""

from collections.abc import Sequence
from typing import Self

import fastembed

from app import config
from app.domain import errors
from app.domain import rag
from app.ports import sparse_embedding


class FastEmbedSparseEmbedding(sparse_embedding.SparseEmbedding):
    """Produces term weights; the vector store applies the IDF."""

    def __init__(
        self, model: fastembed.SparseTextEmbedding, model_name: str
    ) -> None:
        """Initializes the adapter.

        Args:
            model: The loaded FastEmbed sparse model.
            model_name: Its identifier.
        """
        self._model = model
        self._model_name = model_name

    @classmethod
    def load(cls, settings: config.EmbeddingSettings) -> Self:
        """Loads the sparse model from the configured cache directory.

        Args:
            settings: Model name, cache directory and download policy.

        Returns:
            The adapter.

        Raises:
            errors.EmbeddingError: If the model cannot be loaded, e.g. it is
                missing and downloads are forbidden.
        """
        try:
            model = fastembed.SparseTextEmbedding(
                settings.sparse_model_name,
                cache_dir=str(settings.cache_dir),
                local_files_only=settings.local_files_only,
            )
        except ValueError as exc:
            raise errors.EmbeddingError(
                f"Sparse model {settings.sparse_model_name!r} is not "
                "available in DOCINTEL_EMBEDDINGS__CACHE_DIR."
            ) from exc
        return cls(model, settings.sparse_model_name)

    @property
    def model_name(self) -> str:
        """Returns the identifier of the loaded model.

        Returns:
            The model name.
        """
        return self._model_name

    def embed_documents(self, texts: Sequence[str]) -> list[rag.SparseVector]:
        """Weights the terms of passages to be stored.

        Args:
            texts: The passages.

        Returns:
            One sparse vector per passage, in order.
        """
        return [
            _sparse(embedding)
            for embedding in self._model.passage_embed(list(texts))
        ]

    def embed_query(self, text: str) -> rag.SparseVector:
        """Weights the terms of a question.

        Args:
            text: The question.

        Returns:
            The question's sparse vector.
        """
        return _sparse(next(iter(self._model.query_embed(text))))


def _sparse(embedding: fastembed.SparseEmbedding) -> rag.SparseVector:
    """Converts FastEmbed's arrays to the domain's sparse vector.

    Args:
        embedding: FastEmbed's sparse output.

    Returns:
        The sparse vector.
    """
    return rag.SparseVector(
        indices=tuple(int(i) for i in embedding.indices),
        values=tuple(float(v) for v in embedding.values),
    )
