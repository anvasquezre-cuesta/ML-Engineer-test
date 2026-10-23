"""Ports the services depend on.

Protocols rather than ABCs: a test fake only needs the right methods, and mypy
checks that adapters conform. Implementations live in ``app.adapters``.
"""

from collections.abc import Iterator, Sequence
from typing import Protocol

from app.domain.models import (
    Chunk,
    EntitySpan,
    NameMatch,
    OcrWord,
    PageImage,
    RetrievedChunk,
)


class PdfRenderer(Protocol):
    def page_count(self, pdf: bytes) -> int:
        """Open the PDF and return its page count; raise ``InvalidDocument`` if unreadable."""
        ...

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        """Yield every page in order, starting at index 0."""
        ...


class OCREngine(Protocol):
    def recognize(self, page: PageImage) -> list[OcrWord]:
        """Return the words on the page with boxes in the image's pixels."""
        ...


class NERModel(Protocol):
    def find_persons(self, texts: Sequence[str]) -> list[list[EntitySpan]]:
        """For each text, in order, the person entities as character spans of that text."""
        ...


class NameMatcher(Protocol):
    def match(self, extracted: Sequence[str], candidates: Sequence[str]) -> list[NameMatch]:
        """Return every (extracted, candidate) pair at or above the threshold."""
        ...


class Chunker(Protocol):
    def split(self, text: str) -> list[str]:
        """Split one page of text into chunks that never cut a word."""
        ...


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one normalised vector per text."""
        ...


class VectorStore(Protocol):
    def replace_document(
        self, doc_id: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        """Drop any chunks stored for ``doc_id``, store these, and return how many."""
        ...

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        """Return up to ``top_k`` chunks, most similar first."""
        ...


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:
        """Return the model's reply; raise ``UpstreamUnavailable`` after retries."""
        ...
