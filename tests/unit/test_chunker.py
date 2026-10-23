import itertools

import pytest

from app.services.chunking import WordWindowChunker


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


@pytest.mark.parametrize(
    "text",
    [
        _words(149),
        _words(150),
        _words(151),
        _words(1000),
        "Supercalifragilisticexpialidocious antidisestablishmentarianism " * 40,
        "Dr. Fatima Al-Rashidi (PI): $450K; O'Sullivan, María José Ødegård — ok. " * 20,
        "line one\nline two\n\n\tafter a tab  and   spaces " * 30,
    ],
)
@pytest.mark.parametrize(("size", "overlap"), [(150, 30), (50, 10), (7, 0), (2, 1)])
def test_chunker_never_splits_words(text: str, size: int, overlap: int) -> None:
    words = text.split()

    chunks = WordWindowChunker(size, overlap).split(text)

    chunk_words = [chunk.split() for chunk in chunks]
    assert all(len(cw) <= size for cw in chunk_words)
    # Every chunk is a contiguous run of the original words, so no word is ever cut...
    for cw in chunk_words:
        assert any(words[i : i + len(cw)] == cw for i in range(len(words)))
    # ...and together the chunks cover every word, in order.
    assert {w for cw in chunk_words for w in cw} == set(words)
    assert chunk_words[0][0] == words[0]
    assert chunk_words[-1][-1] == words[-1]


@pytest.mark.parametrize(("size", "overlap"), [(150, 30), (10, 3), (5, 0)])
def test_overlap_between_neighbours_is_exact(size: int, overlap: int) -> None:
    chunks = [c.split() for c in WordWindowChunker(size, overlap).split(_words(437))]

    for previous, current in itertools.pairwise(chunks):
        if overlap:
            assert previous[-overlap:] == current[:overlap]
        else:
            assert previous[-1] != current[0]


def test_a_page_under_the_window_is_one_chunk() -> None:
    # The sample pages hold 129-149 words: one chunk each at 150, so sources cite one page.
    assert len(WordWindowChunker(150, 30).split(_words(149))) == 1


def test_no_trailing_chunk_made_only_of_overlap() -> None:
    chunks = WordWindowChunker(10, 3).split(_words(17))  # windows 0-9 and 7-16

    assert [len(c.split()) for c in chunks] == [10, 10]


@pytest.mark.parametrize("text", ["", "   ", "\n\t \n"])
def test_empty_pages_yield_no_chunks(text: str) -> None:
    assert WordWindowChunker(150, 30).split(text) == []


@pytest.mark.parametrize(("size", "overlap"), [(10, 10), (10, 11), (0, 0), (10, -1)])
def test_invalid_window_is_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        WordWindowChunker(size, overlap)
