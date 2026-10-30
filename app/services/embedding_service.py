"""Embeddings for RAG: the sentence-transformers model is loaded once, on first use."""

from functools import lru_cache
from typing import Protocol

from app.config import get_settings


class Embedder(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


@lru_cache
def _load_model(name: str, device: str):
    """Load a sentence-transformers model once per (name, device)."""
    from sentence_transformers import SentenceTransformer  # slow import: only when used

    return SentenceTransformer(name, device=device)


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunks (unit-length vectors)."""
    settings = get_settings()
    model = _load_model(settings.embedding_model, settings.embedding_device)
    return model.encode(texts, normalize_embeddings=True).tolist()


def get_query_embedding(text: str) -> list[float]:
    """Embed a single query."""
    return get_embeddings([text])[0]
