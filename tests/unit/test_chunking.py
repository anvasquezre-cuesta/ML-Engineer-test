import pytest

from app.services.rag_service import chunk_text

TEXT = " ".join(f"token{i:03d}" for i in range(300))


def test_chunks_never_split_words():
    vocabulary = set(TEXT.split())
    for chunk in chunk_text(TEXT, size=120, overlap=20):
        assert len(chunk) <= 120
        assert set(chunk.split()) <= vocabulary


def test_every_word_is_covered_in_order():
    chunks = chunk_text(TEXT, size=120, overlap=20)
    seen = []
    for chunk in chunks:
        for word in chunk.split():
            if not seen or word > seen[-1]:
                seen.append(word)
    assert seen == TEXT.split()


def test_overlap_repeats_tail_of_previous_chunk():
    first, second = chunk_text(TEXT, size=120, overlap=20)[:2]
    assert first.split()[-1] in second.split()


def test_word_longer_than_chunk_is_kept_whole():
    assert chunk_text("a " + "b" * 50 + " c", size=10, overlap=0) == ["a", "b" * 50, "c"]


def test_empty_text():
    assert chunk_text("   ", size=100, overlap=10) == []


def test_bad_size():
    with pytest.raises(ValueError):
        chunk_text("x", size=0, overlap=0)
