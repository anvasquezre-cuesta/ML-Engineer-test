"""
Module: tests.unit.test_text_chunker
Path: tests/unit/test_text_chunker.py
Description: Unit tests for word-safe RAG text chunking.
"""

from app.config import Settings
from app.services.text_chunker import TextChunker


def test_split_text_creates_multiple_chunks() -> None:
    chunker = TextChunker(Settings(rag_chunk_size=20, rag_chunk_overlap=5))

    chunks = chunker.split_text(
        "This is a simple document containing enough words to create multiple chunks."
    )

    assert len(chunks) > 1


def test_split_text_does_not_break_words() -> None:
    chunker = TextChunker(Settings(rag_chunk_size=20, rag_chunk_overlap=5))
    text = "Alice visited the hospital yesterday."

    chunks = chunker.split_text(text)

    assert "hospital" in chunks[1] or "hospital" in chunks[0]
    assert "".join(chunks).replace(" ", "") != ""


def test_split_text_handles_whitespace_separators() -> None:
    chunker = TextChunker(Settings(rag_chunk_size=30, rag_chunk_overlap=5))

    chunks = chunker.split_text(
        "First paragraph.\n\nSecond paragraph.\nThird paragraph."
    )

    assert chunks
    assert all(chunk.strip() == chunk for chunk in chunks)


def test_split_text_keeps_long_words_intact() -> None:
    long_word = "supercalifragilisticexpialidocious"
    chunker = TextChunker(Settings(rag_chunk_size=10, rag_chunk_overlap=2))

    chunks = chunker.split_text(f"Short {long_word} word.")

    assert any(long_word in chunk for chunk in chunks)
