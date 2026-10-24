"""Sentence Transformers embedding adapter."""

from app.services.embedding_service import EmbeddingProvider

import sentence_transformers


class Embedder(EmbeddingProvider):
    def __init__(self, model_name: str):
        self.model = sentence_transformers.SentenceTransformer(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    def embed_query(self, text: str) -> list[float]:
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
