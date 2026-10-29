"""Cut a document's OCR pages into chunks for RAG (TRD ADR-015).

Only logical units are split points, largest first: paragraph (OCR block) → sentence →
word. Units are packed whole; a unit that does not fit closes the chunk and moves whole
to the next one. Visual lines are never split points, chunks never span pages and a word
is never cut.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import groupby

from app.domain.document import Page, Word
from app.domain.names import HONORIFICS
from app.domain.page_text import LINE_SEPARATOR, WORD_SEPARATOR

# 64 bits of the SHA-256: collisions are negligible for any realistic corpus (ADR-007).
DOCUMENT_ID_LENGTH = 16
SENTENCE_ENDINGS = (".", "?", "!")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class Chunk:
    """A piece of one page of a document, the unit that is embedded, searched and cited."""

    document_id: str
    file_name: str
    page: int
    chunk_index: int
    text: str

    def __post_init__(self) -> None:
        if self.page < 0:
            raise ValueError(f"page must be >= 0, got {self.page}")
        if self.chunk_index < 0:
            raise ValueError(f"chunk_index must be >= 0, got {self.chunk_index}")
        if not self.text.strip():
            raise ValueError("chunk text must be non-empty")

    @property
    def id(self) -> str:
        """Unique across documents: the content hash prefixes the chunk number (ADR-007)."""
        return f"{self.document_id}:{self.chunk_index}"

    @property
    def source(self) -> str:
        """How the chunk is cited in ``sources``: file name and 0-based page."""
        return f"{self.file_name}, page {self.page}"


def document_id_for(pdf: bytes) -> str:
    """Identify a document by its content, so the same PDF always gets the same id."""
    return hashlib.sha256(pdf).hexdigest()[:DOCUMENT_ID_LENGTH]


def chunk_document(
    pages: Sequence[Page],
    document_id: str,
    file_name: str,
    max_tokens: int,
    count_tokens: TokenCounter,
) -> tuple[Chunk, ...]:
    """Pack each page's paragraphs into chunks of at most ``max_tokens`` tokens."""
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be >= 1, got {max_tokens}")
    chunks: list[Chunk] = []
    for page in pages:
        for text in _pack(_units(page, max_tokens, count_tokens), max_tokens, count_tokens):
            chunks.append(Chunk(document_id, file_name, page.index, len(chunks), text))
    return tuple(chunks)


def _units(page: Page, max_tokens: int, count_tokens: TokenCounter) -> list[list[Word]]:
    """The page as the largest logical units that fit the budget on their own."""
    units: list[list[Word]] = []
    for _, block_words in groupby(page.words, key=lambda word: word.line_key[0]):
        block = list(block_words)
        if count_tokens(_join(block)) <= max_tokens:
            units.append(block)
            continue
        for sentence in _sentences(block):
            if count_tokens(_join(sentence)) <= max_tokens:
                units.append(sentence)
            else:
                units += [[word] for word in sentence]
    return units


def _sentences(block: list[Word]) -> list[list[Word]]:
    sentences: list[list[Word]] = [[]]
    for word in block:
        sentences[-1].append(word)
        if _ends_sentence(word):
            sentences.append([])
    return [sentence for sentence in sentences if sentence]


def _ends_sentence(word: Word) -> bool:
    """``costs.`` ends a sentence; an honorific such as ``Dr.`` does not."""
    stem = word.text.rstrip("".join(SENTENCE_ENDINGS)).casefold()
    return word.text.endswith(SENTENCE_ENDINGS) and stem not in HONORIFICS


def _pack(units: list[list[Word]], max_tokens: int, count_tokens: TokenCounter) -> list[str]:
    """Greedily join consecutive units while the joined text stays within the budget."""
    texts: list[str] = []
    current: list[Word] = []
    for unit in units:
        candidate = current + unit
        if current and count_tokens(_join(candidate)) > max_tokens:
            texts.append(_join(current))
            candidate = unit
        current = candidate
    if current:
        texts.append(_join(current))
    return texts


def _join(words: list[Word]) -> str:
    """Words joined like the page text: a space within a line, a newline between lines."""
    parts: list[str] = []
    for index, word in enumerate(words):
        if index:
            same_line = word.line_key == words[index - 1].line_key
            parts.append(WORD_SEPARATOR if same_line else LINE_SEPARATOR)
        parts.append(word.text)
    return "".join(parts)
