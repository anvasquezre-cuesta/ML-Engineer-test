"""VectorStore backed by Qdrant."""

from collections.abc import Sequence

import qdrant_client

from app import config
from app.domain import rag
from app.ports import vector_store


class QdrantVectorStore(vector_store.VectorStore):
    """Stores chunks as points keyed by deterministic ids, one collection."""

    def __init__(
        self,
        client: qdrant_client.AsyncQdrantClient,
        settings: config.QdrantSettings,
        collection: str,
        dimension: int,
    ) -> None:
        """Initializes the store.

        Args:
            client: An open Qdrant client.
            settings: Timeouts and retry budget.
            collection: Collection name, specific to the embedding model.
            dimension: Length of the stored vectors.
        """
        self._client = client
        self._settings = settings
        self._collection = collection
        self._dimension = dimension

    async def ensure_collection(self) -> None:  # noqa: DOC501, DOC503
        """Creates the collection and payload indexes if they are missing."""
        raise NotImplementedError

    async def upsert(self, chunks: Sequence[rag.EmbeddedChunk]) -> None:  # noqa: DOC501, DOC503
        """Stores chunks; writing the same chunk twice leaves one copy.

        Args:
            chunks: The chunks and their vectors.
        """
        raise NotImplementedError

    async def get_document(  # noqa: DOC501, DOC503
        self, document_key: str
    ) -> rag.DocumentRecord | None:
        """Reads what is stored for one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The document record, or ``None`` if nothing is stored for it.
        """
        raise NotImplementedError

    async def list_documents(self) -> list[rag.DocumentRecord]:  # noqa: DOC501, DOC503
        """Lists every stored document.

        Returns:
            One record per document.
        """
        raise NotImplementedError

    async def delete_document(self, document_key: str) -> int:  # noqa: DOC501, DOC503
        """Deletes every chunk of one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The number of chunks deleted.
        """
        raise NotImplementedError

    async def search(  # noqa: DOC501, DOC503
        self, vector: rag.Vector, top_k: int
    ) -> list[rag.ScoredChunk]:
        """Finds the chunks closest to ``vector``.

        Args:
            vector: The query vector.
            top_k: Maximum number of chunks to return.

        Returns:
            The closest chunks, best first.
        """
        raise NotImplementedError
