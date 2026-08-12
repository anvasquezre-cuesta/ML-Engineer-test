"""Vector store for RAG.

Use whatever store you like — an embedded/local one (e.g. Chroma) is fine; a
separate service (e.g. Qdrant) is a bonus. Implement this. Reminders (graded):
any connection/config comes from config, not hardcoded; IDs must be unique
across documents (a second ingest must not overwrite the first); wrap the client
so failures surface as meaningful errors.
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
