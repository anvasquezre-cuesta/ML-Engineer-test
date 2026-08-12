"""Vector store (e.g. Qdrant) for RAG.

Implement this. Reminders (graded): connection parameters come from config, not
hardcoded; point IDs must be unique across documents (a second ingest must not
overwrite the first); wrap the client so failures surface as meaningful errors.
"""


def init_collection() -> None:
    """Create the collection if it does not exist."""
    raise NotImplementedError


def store_document_chunks(
    chunks: list[str], metadata: list[dict] | None = None
) -> None:
    """Embed and store chunks with their metadata."""
    raise NotImplementedError


def search_similar(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Return the most similar chunks as ``{"text", "score"}``."""
    raise NotImplementedError
