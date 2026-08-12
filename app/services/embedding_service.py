"""Embeddings for RAG.

Implement this. Load the embedding model ONCE (not per request) and reuse it.
"""


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunks."""
    raise NotImplementedError


def get_query_embedding(text: str) -> list[float]:
    """Embed a single query."""
    raise NotImplementedError
