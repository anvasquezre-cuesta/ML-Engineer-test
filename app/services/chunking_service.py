"""Split OCR page text on word boundaries within the embedding token budget."""

from dataclasses import dataclass
import re
from typing import Protocol


class Tokenizer(Protocol):
    def encode(self, text: str, *, add_special_tokens: bool, truncation: bool) -> list[int]: ...


class ChunkingError(ValueError):
    """Text cannot be chunked without truncation or splitting a word."""


class ChunkingLimitError(ChunkingError):
    """A page exceeds a configured chunking resource limit."""


@dataclass(frozen=True)
class TextChunk:
    """A page-local, whole-word substring, including its exact source offsets."""

    page_number: int
    index_in_page: int
    text: str
    char_start: int
    char_end: int
    token_count: int


class TokenAwareChunker:
    """Greedily group complete words, with a bounded whole-word overlap.

    The budget includes the tokenizer's special tokens. Actual candidate strings
    are tokenized with truncation disabled; a result is never silently shortened
    to make it fit. Overlap can be smaller than requested at a word or page edge.
    """

    def __init__(
        self,
        tokenizer: Tokenizer,
        *,
        max_tokens: int = 128,
        overlap_tokens: int = 32,
        model_max_tokens: int | None = None,
        max_page_chars: int = 100_000,
        max_page_chunks: int = 1000,
    ) -> None:
        if (type(max_tokens) is not int or type(overlap_tokens) is not int
                or type(max_page_chars) is not int or type(max_page_chunks) is not int
                or max_page_chars <= 0 or max_page_chunks <= 0):
            raise ValueError("Chunking limits must be valid integers")
        if model_max_tokens is not None and (
            type(model_max_tokens) is not int or model_max_tokens <= 0 or max_tokens > model_max_tokens
        ):
            raise ValueError("Chunk budget exceeds the model limit")
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.max_page_chars = max_page_chars
        self.max_page_chunks = max_page_chunks
        special_tokens = self._count("", special=True)
        if max_tokens <= special_tokens or not 0 <= overlap_tokens < max_tokens - special_tokens:
            raise ValueError("Chunk budget and overlap leave no room for content")

    def _count(self, text: str, *, special: bool) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=special, truncation=False))

    def split_page(self, text: str, page_number: int) -> list[TextChunk]:
        """Return page-local chunks, preserving the page number and source text."""
        if not isinstance(text, str) or type(page_number) is not int or page_number < 0:
            raise ValueError("Expected page text and a non-negative page number")
        if len(text) > self.max_page_chars:
            raise ChunkingLimitError("Page exceeds the configured character limit")
        words = list(re.finditer(r"\S+", text))
        for match in words:
            word = match.group()
            tokens = self.tokenizer.encode(word, add_special_tokens=False, truncation=False)
            if not tokens:
                raise ChunkingError("A non-whitespace word produced no model tokens")
            if self._count(word, special=True) > self.max_tokens:
                raise ChunkingError("A word exceeds the configured token budget")
        chunks = []
        start = 0
        while start < len(words):
            first = words[start]
            end = start + 1
            while end < len(words):
                candidate = text[first.start():words[end].end()]
                if self._count(candidate, special=True) > self.max_tokens:
                    break
                end += 1

            last = words[end - 1]
            fragment = text[first.start():last.end()]
            if len(chunks) >= self.max_page_chunks:
                raise ChunkingLimitError("Page exceeds the configured chunk limit")
            chunks.append(TextChunk(
                page_number=page_number,
                index_in_page=len(chunks),
                text=fragment,
                char_start=first.start(),
                char_end=last.end(),
                token_count=self._count(fragment, special=True),
            ))
            if end == len(words):
                break

            # Keep only a suffix within the overlap budget and always advance.
            next_start = end
            while next_start > start + 1:
                candidate = text[words[next_start - 1].start():last.end()]
                if self._count(candidate, special=False) > self.overlap_tokens:
                    break
                next_start -= 1

            # An overlapping suffix plus the next word may exceed the budget.
            # Shorten the suffix so the next chunk can include a new word.
            while next_start < end:
                candidate = text[words[next_start].start():words[end].end()]
                if self._count(candidate, special=True) <= self.max_tokens:
                    break
                next_start += 1
            start = next_start
        return chunks
