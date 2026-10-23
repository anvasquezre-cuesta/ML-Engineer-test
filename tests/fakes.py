"""Hand-written fakes for the domain Protocols.

Each is a tiny working implementation, so tests read like the domain and the
same fake serves many tests. They also record calls for assertions.
"""

import hashlib
import math
from collections.abc import Iterator, Sequence

from app.domain.models import (
    Box,
    Chunk,
    EntitySpan,
    OcrPage,
    OcrWord,
    PageImage,
    PageWord,
    RetrievedChunk,
)


def blank_page(index: int, *, dpi: int = 72, rotation: int = 0) -> PageImage:
    """A US Letter page; at the default 72 DPI one pixel is one point."""
    width_px, height_px = round(612 * dpi / 72), round(792 * dpi / 72)
    return PageImage(
        index=index,
        width_pt=612.0,
        height_pt=792.0,
        rotation=rotation,
        dpi=dpi,
        width_px=width_px,
        height_px=height_px,
        pixels=b"",  # fakes never read the pixels
    )


class FakeRenderer:
    """Renders the given pages; with ``error`` set, opening the document raises it."""

    def __init__(self, pages: list[PageImage], error: Exception | None = None) -> None:
        self.pages = pages
        self.error = error
        self.page_count_calls = 0

    def page_count(self, pdf: bytes) -> int:
        self.page_count_calls += 1
        if self.error is not None:
            raise self.error
        return len(self.pages)

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        yield from self.pages


class FakeOCR:
    """Returns ``words_by_page[index]`` for each page and records which pages it saw."""

    def __init__(self, words_by_page: dict[int, list[OcrWord]] | None = None) -> None:
        self.words_by_page = words_by_page or {}
        self.seen_pages: list[int] = []

    def recognize(self, page: PageImage) -> list[OcrWord]:
        self.seen_pages.append(page.index)
        return self.words_by_page.get(page.index, [])


def ocr_word(
    text: str, x0: float, y0: float, x1: float, y1: float, line: int = 1, conf: float = 95.0
) -> OcrWord:
    return OcrWord(text=text, box_px=Box(x0, y0, x1, y1), confidence=conf, line_key=(1, 1, line))


CHAR_WIDTH_PT = 5.0
LINE_HEIGHT_PT = 10.0


def words_on_line(
    text: str, line: int, *, x: float = 50.0, conf: float | Sequence[float] = 95.0
) -> list[PageWord]:
    """Lay out ``text`` word by word on one line: 5 pt per character, one space between words."""
    y0 = 100.0 + line * 2 * LINE_HEIGHT_PT
    tokens = text.split()
    confidences = [conf] * len(tokens) if isinstance(conf, float | int) else list(conf)
    words = []
    for token, confidence in zip(tokens, confidences, strict=True):
        x1 = x + len(token) * CHAR_WIDTH_PT
        words.append(
            PageWord(
                text=token,
                box=Box(x, y0, x1, y0 + LINE_HEIGHT_PT),
                confidence=confidence,
                line_key=(1, 1, line),
            )
        )
        x = x1 + CHAR_WIDTH_PT
    return words


def ocr_page(index: int, *lines: list[PageWord]) -> OcrPage:
    return OcrPage(
        index=index,
        width_pt=612.0,
        height_pt=792.0,
        words=tuple(word for line in lines for word in line),
    )


class FakeNER:
    """Tags every occurrence of the given strings as a person and records its calls."""

    def __init__(self, *persons: str) -> None:
        self.persons = persons
        self.calls: list[list[str]] = []

    def find_persons(self, texts: Sequence[str]) -> list[list[EntitySpan]]:
        self.calls.append(list(texts))
        return [self._find(text) for text in texts]

    def _find(self, text: str) -> list[EntitySpan]:
        spans = []
        for person in self.persons:
            start = text.find(person)
            while start != -1:
                spans.append(EntitySpan(person, start, start + len(person)))
                start = text.find(person, start + 1)
        return sorted(spans, key=lambda s: s.start_char)


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are close. Records calls."""

    DIMENSIONS = 64

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.DIMENSIONS
        for word in text.lower().split():
            digest = hashlib.sha256(word.strip(".,:;?!").encode()).digest()
            vector[digest[0] % self.DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class FakeLLM:
    """Returns a canned answer and records every (system, user) prompt it receives."""

    def __init__(self, answer: str = "Robert Chen.") -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.answer


class FailingStore:
    """A ``VectorStore`` whose every call raises ``error``."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def replace_document(
        self, doc_id: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        raise self.error

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        raise self.error

    def count(self) -> int:
        raise self.error


class InMemoryVectorStore:
    """A ``VectorStore`` with the same ID and replace semantics as the Chroma adapter."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[Chunk, list[float]]] = {}

    def replace_document(
        self, doc_id: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        self.rows = {k: v for k, v in self.rows.items() if v[0].doc_id != doc_id}
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.rows[chunk.chunk_id] = (chunk, list(vector))
        return len(chunks)

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        scored = [
            RetrievedChunk(chunk, max(0.0, sum(a * b for a, b in zip(vector, v, strict=True))))
            for chunk, v in self.rows.values()
        ]
        return sorted(scored, key=lambda r: -r.similarity)[:top_k]

    def count(self) -> int:
        return len(self.rows)
