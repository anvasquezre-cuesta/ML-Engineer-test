"""Ports: what the application needs from the outside world (TRD ADR-001).

Signatures use domain types only, so adapters can be swapped without touching use cases.
"""

from collections.abc import Iterator, Sequence
from typing import Protocol

from app.domain.chunking import Chunk
from app.domain.document import Page, PageImage, PdfInfo
from app.domain.grounding import LlmReply, Prompt
from app.domain.persons import PersonSpan


class PdfRasterizer(Protocol):
    """Turns PDF bytes into page images."""

    def probe(self, pdf: bytes) -> PdfInfo:
        """Read page count and encryption without rendering; raises ``PdfUnreadable``."""
        ...

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        """Yield every page (index 0..n-1); raises ``PdfUnreadable`` / ``PdfEncrypted``."""
        ...


class OcrEngine(Protocol):
    """Reads the words on a page image."""

    def recognize(self, image: PageImage) -> Page:
        """Return the page's words with boxes in PDF points; raises ``OcrUnavailable``."""
        ...


class PersonNameRecognizer(Protocol):
    """Finds person names in text."""

    def recognize(self, text: str) -> list[PersonSpan]:
        """Return PERSON spans, honorifics trimmed; raises ``NerModelUnavailable``."""
        ...


class Embedder(Protocol):
    """Turns text into vectors whose closeness reflects meaning, and counts its tokens."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per stored text; raises ``EmbeddingModelUnavailable``."""
        ...

    def embed_question(self, text: str) -> list[float]:
        """The vector of a question, comparable with passage vectors."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens the model reads for ``text`` (sizes chunks, ADR-015)."""
        ...


class VectorStore(Protocol):
    """Keeps chunks with their vectors; every method raises ``VectorStoreUnavailable``."""

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Drop every stored chunk of ``document_id``, then store ``chunks`` (ADR-007)."""
        ...

    def search(self, embedding: Sequence[float], limit: int) -> list[Chunk]:
        """Up to ``limit`` chunks nearest to ``embedding``, nearest first."""
        ...

    def all_chunks(self) -> list[Chunk]:
        """Every stored chunk (BM25 ranks them per question — ADR-014)."""
        ...


class Reranker(Protocol):
    """Scores how well each passage answers a question, reading both together."""

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        """One score per text, in input order (higher = more relevant); ``[]`` for none."""
        ...


class AnswerGenerator(Protocol):
    """Writes an answer from a prompt; never chooses what runs next (ADR-006)."""

    def generate(self, prompt: Prompt) -> LlmReply:
        """Raises ``LlmNotConfigured``, ``LlmTimeout``, ``LlmRateLimited`` or ``LlmUnavailable``."""
        ...
