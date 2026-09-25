"""Port for storing, reading, deleting and searching document chunks."""

import abc
from collections.abc import Sequence

from app.domain import rag


class VectorStore(abc.ABC):
    """Vector store keyed by document, with unique ids across documents.

    Every method may raise ``VectorStoreUnavailableError`` or
    ``VectorStoreTimeoutError`` once the adapter's retries are exhausted.
    """

    @abc.abstractmethod
    async def ensure_collection(self) -> None:
        """Creates the collection and payload indexes if they are missing."""

    @abc.abstractmethod
    async def upsert(self, chunks: Sequence[rag.EmbeddedChunk]) -> None:
        """Stores chunks; writing the same chunk twice leaves one copy.

        Args:
            chunks: The chunks and their vectors.
        """

    @abc.abstractmethod
    async def get_document(
        self, document_key: str
    ) -> rag.DocumentRecord | None:
        """Reads what is stored for one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The document record, or ``None`` if nothing is stored for it.
        """

    @abc.abstractmethod
    async def list_documents(self) -> list[rag.DocumentRecord]:
        """Lists every stored document.

        Returns:
            One record per document.
        """

    @abc.abstractmethod
    async def delete_document(self, document_key: str) -> int:
        """Deletes every chunk of one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The number of chunks deleted.
        """

    @abc.abstractmethod
    async def hybrid_search(
        self, query: rag.SearchQuery, top_k: int
    ) -> list[rag.ScoredChunk]:
        """Finds the best chunks by fusing dense and keyword rankings.

        Keyword statistics count only the chunks currently stored, so the
        ranking does not depend on what was replaced or deleted before.

        Args:
            query: The question's dense and sparse embeddings.
            top_k: Maximum number of chunks to return.

        Returns:
            The best chunks, best first.
        """
