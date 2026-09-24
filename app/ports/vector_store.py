"""Port for storing, reading, deleting and searching document chunks."""

import abc
from collections.abc import Sequence

from app.domain.rag import DocumentRecord
from app.domain.rag import EmbeddedChunk
from app.domain.rag import ScoredChunk
from app.domain.rag import Vector


class VectorStore(abc.ABC):
    """Vector store keyed by document, with unique ids across documents.

    Every method may raise ``VectorStoreUnavailableError`` or
    ``VectorStoreTimeoutError`` once the adapter's retries are exhausted.
    """

    @abc.abstractmethod
    async def ensure_collection(self) -> None:
        """Creates the collection and payload indexes if they are missing."""

    @abc.abstractmethod
    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Stores chunks; writing the same chunk twice leaves one copy.

        Args:
            chunks: The chunks and their vectors.
        """

    @abc.abstractmethod
    async def get_document(self, document_key: str) -> DocumentRecord | None:
        """Reads what is stored for one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The document record, or ``None`` if nothing is stored for it.
        """

    @abc.abstractmethod
    async def list_documents(self) -> list[DocumentRecord]:
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
    async def search(self, vector: Vector, top_k: int) -> list[ScoredChunk]:
        """Finds the chunks closest to ``vector``.

        Args:
            vector: The query vector.
            top_k: Maximum number of chunks to return.

        Returns:
            The closest chunks, best first.
        """
