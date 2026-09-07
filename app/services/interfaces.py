"""The seams we swap in tests. Anything CPU/network heavy sits behind one of these."""

from typing import Protocol

from app.models.domain import Page, RetrievedChunk


class OcrEngine(Protocol):
    def run(self, pdf: bytes) -> list[Page]: ...


class NerExtractor(Protocol):
    def person_names(self, text: str) -> list[str]: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def add(
        self, ids: list[str], texts: list[str], embeddings: list[list[float]], sources: list[str]
    ) -> None: ...

    def query(self, embedding: list[float], top_k: int) -> list[RetrievedChunk]: ...


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str: ...
