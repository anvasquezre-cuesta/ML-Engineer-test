"""Tests for deterministic chunk point ids."""

import dataclasses

from app.domain import ids
from app.domain import rag

CHUNK = rag.Chunk(
    document_key="memo.pdf",
    content_hash="a" * 64,
    page_number=0,
    chunk_index=0,
    start_char=0,
    end_char=5,
    text="hello",
    strategy="sentence",
)


def test_same_position_in_another_document_gets_another_id() -> None:
    other = dataclasses.replace(CHUNK, document_key="minutes.pdf")
    assert ids.chunk_point_id(CHUNK) != ids.chunk_point_id(other)


def test_id_depends_only_on_document_hash_and_position() -> None:
    resplit = dataclasses.replace(CHUNK, text="hello world", end_char=11)
    assert ids.chunk_point_id(CHUNK) == ids.chunk_point_id(resplit)
