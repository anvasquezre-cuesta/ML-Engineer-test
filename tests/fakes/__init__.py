"""In-memory fakes of the application ports (CONSTITUTION §7: fakes, not mocks)."""

import math
from collections.abc import Iterator, Mapping, Sequence

from app.domain.chunking import Chunk
from app.domain.document import Page, PageImage, PdfInfo, Word
from app.domain.geometry import BoundingBox
from app.domain.grounding import LlmReply, Prompt
from app.domain.persons import PersonSpan

PAGE_WIDTH_PT = 612.0
PAGE_HEIGHT_PT = 792.0


class FakeRasterizer:
    """Pretends every PDF has ``pages`` blank Letter-size pages."""

    def __init__(self, pages: int, encrypted: bool = False) -> None:
        self.pages = pages
        self.encrypted = encrypted
        self.probe_calls = 0
        self.render_calls = 0

    def probe(self, pdf: bytes) -> PdfInfo:
        self.probe_calls += 1
        return PdfInfo(page_count=self.pages, encrypted=self.encrypted)

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        self.render_calls += 1
        for index in range(self.pages):
            yield PageImage(index, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, dpi, b"")


class FakeOcrEngine:
    """Returns scripted words per page index; records which pages it was asked for."""

    def __init__(
        self,
        words_by_page: Mapping[int, Sequence[Word]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.words_by_page = dict(words_by_page or {})
        self.error = error
        self.calls: list[int] = []

    def recognize(self, image: PageImage) -> Page:
        self.calls.append(image.index)
        if self.error is not None:
            raise self.error
        words = tuple(self.words_by_page.get(image.index, ()))
        return Page(image.index, image.width_pt, image.height_pt, words)


class FakeRecognizer:
    """Finds each scripted name wherever it occurs verbatim in the text."""

    def __init__(self, names: Sequence[str] = ()) -> None:
        self.names = list(names)
        self.calls = 0

    def recognize(self, text: str) -> list[PersonSpan]:
        self.calls += 1
        spans = []
        for name in self.names:
            start = text.find(name)
            while start != -1:
                spans.append(PersonSpan(start, start + len(name), name))
                start = text.find(name, start + 1)
        return sorted(spans, key=lambda s: s.start)


def line_of_words(line: int, text: str, y: float | None = None) -> list[Word]:
    """Words of ``text`` on one line, laid out left to right at 8 pt per character."""
    top = line * 20.0 if y is None else y
    words, x = [], 72.0
    for token in text.split():
        width = 8.0 * len(token)
        words.append(Word(token, BoundingBox(x, top, width, 12.0), 95.0, (1, 1, line)))
        x += width + 4.0
    return words


class FakeEmbedder:
    """Letter-frequency vectors: texts sharing letters are close; whitespace-word tokens."""

    def __init__(self) -> None:
        self.passage_calls = 0
        self.question_calls = 0

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        self.passage_calls += 1
        return [_letter_vector(text) for text in texts]

    def embed_question(self, text: str) -> list[float]:
        self.question_calls += 1
        return _letter_vector(text)

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class InMemoryVectorStore:
    """Keeps chunks in a dict; cosine search; raises ``error`` on every call when set."""

    def __init__(self, error: Exception | None = None) -> None:
        self.rows: dict[str, tuple[Chunk, list[float]]] = {}
        self.error = error
        self.search_calls = 0

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self._fail_if_set()
        self.rows = {k: v for k, v in self.rows.items() if v[0].document_id != document_id}
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self.rows[chunk.id] = (chunk, list(embedding))

    def search(self, embedding: Sequence[float], limit: int) -> list[Chunk]:
        self._fail_if_set()
        self.search_calls += 1
        ranked = sorted(self.rows.values(), key=lambda row: -_cosine(embedding, row[1]))
        return [chunk for chunk, _ in ranked[:limit]]

    def all_chunks(self) -> list[Chunk]:
        self._fail_if_set()
        return [chunk for chunk, _ in self.rows.values()]

    def _fail_if_set(self) -> None:
        if self.error is not None:
            raise self.error


def _letter_vector(text: str) -> list[float]:
    counts = [float(text.casefold().count(letter)) for letter in "abcdefghijklmnopqrstuvwxyz"]
    norm = math.sqrt(sum(c * c for c in counts)) or 1.0
    return [c / norm for c in counts]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class FakeReranker:
    """Scores each text from a script (unknown texts score ``default``); records calls."""

    def __init__(self, scores: Mapping[str, float] | None = None, default: float = 0.0) -> None:
        self.scores = dict(scores or {})
        self.default = default
        self.calls: list[list[str]] = []

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        self.calls.append(list(texts))
        return [self.scores.get(text, self.default) for text in texts]


class FakeAnswerGenerator:
    """Replies with a scripted text (or raises ``error``); records the prompts it got."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[Prompt] = []

    def generate(self, prompt: Prompt) -> LlmReply:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return LlmReply(self.reply, "fake-llm", prompt_tokens=100, completion_tokens=10)
