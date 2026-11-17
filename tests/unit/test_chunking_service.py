import re
import random

import pytest

from app.services.chunking_service import ChunkingError, ChunkingLimitError, TokenAwareChunker


class WordTokenizer:
    def encode(self, text, *, add_special_tokens, truncation):
        assert truncation is False
        tokens = re.findall(r"\S+", text)
        return [0, *range(len(tokens)), 1] if add_special_tokens else list(range(len(tokens)))


class CharacterTokenizer:
    def encode(self, text, *, add_special_tokens, truncation):
        assert truncation is False
        tokens = list(re.sub(r"\s+", "", text))
        return [0, *range(len(tokens)), 1] if add_special_tokens else list(range(len(tokens)))


def test_empty_pages_do_not_produce_chunks():
    chunker = TokenAwareChunker(WordTokenizer())
    assert chunker.split_page("", 0) == []
    assert chunker.split_page("  \n\t ", 3) == []


def test_whole_words_offsets_overlap_and_original_page_are_preserved():
    text = "one  two\nthree four five six seven eight nine ten eleven"
    chunker = TokenAwareChunker(WordTokenizer(), max_tokens=6, overlap_tokens=2, model_max_tokens=10)
    chunks = chunker.split_page(text, 3)
    assert [chunk.text for chunk in chunks] == [
        "one  two\nthree four", "three four five six", "five six seven eight", "seven eight nine ten", "nine ten eleven",
    ]
    assert [chunk.index_in_page for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_number == 3 and chunk.token_count <= 6 for chunk in chunks)
    assert all(text[chunk.char_start:chunk.char_end] == chunk.text for chunk in chunks)


def test_overlap_is_shortened_if_the_next_word_needs_the_full_budget():
    chunker = TokenAwareChunker(CharacterTokenizer(), max_tokens=10, overlap_tokens=4)
    chunks = chunker.split_page("aaaa bbbb cccccccc", 1)
    assert [chunk.text for chunk in chunks] == ["aaaa bbbb", "cccccccc"]
    assert all(chunk.token_count == 10 for chunk in chunks)


def test_a_single_overlong_word_is_rejected_without_splitting():
    chunker = TokenAwareChunker(CharacterTokenizer(), max_tokens=6, overlap_tokens=1)
    with pytest.raises(ChunkingError, match="word exceeds"):
        chunker.split_page("ok abcde", 0)


def test_overlap_can_be_disabled():
    chunker = TokenAwareChunker(WordTokenizer(), max_tokens=4, overlap_tokens=0)
    assert [chunk.text for chunk in chunker.split_page("one two three four five", 0)] == [
        "one two", "three four", "five",
    ]


@pytest.mark.parametrize("options", [
    {"max_tokens": 2, "overlap_tokens": 0},
    {"max_tokens": 6, "overlap_tokens": -1},
    {"max_tokens": 6, "overlap_tokens": 4},
    {"max_tokens": 6, "overlap_tokens": 0, "model_max_tokens": 5},
    {"max_tokens": True, "overlap_tokens": 0},
    {"max_tokens": 6, "overlap_tokens": 0, "max_page_chars": 0},
    {"max_tokens": 6, "overlap_tokens": 0, "max_page_chunks": -1},
])
def test_invalid_token_limits_are_rejected(options):
    with pytest.raises(ValueError):
        TokenAwareChunker(WordTokenizer(), **options)


def test_invalid_page_is_rejected():
    chunker = TokenAwareChunker(WordTokenizer())
    with pytest.raises(ValueError):
        chunker.split_page("text", -1)


def test_page_and_chunk_limits_are_inclusive():
    chunker = TokenAwareChunker(
        WordTokenizer(), max_tokens=3, overlap_tokens=0, max_page_chars=7, max_page_chunks=2,
    )
    assert len(chunker.split_page("one two", 0)) == 2
    with pytest.raises(ChunkingLimitError, match="character limit"):
        chunker.split_page("one two ", 0)
    with pytest.raises(ChunkingLimitError, match="chunk limit"):
        chunker.split_page("a b c", 0)


def test_varied_chunk_limits_preserve_every_word_and_bound_overlap():
    randomizer = random.Random(19)
    for _ in range(100):
        words = [f"word{index}" for index in range(randomizer.randint(1, 50))]
        text = " ".join(words)
        budget = randomizer.randint(4, 14)
        overlap = randomizer.randint(0, budget - 3)
        chunks = TokenAwareChunker(WordTokenizer(), max_tokens=budget, overlap_tokens=overlap).split_page(text, 4)
        assert all(chunk.token_count <= budget and text[chunk.char_start:chunk.char_end] == chunk.text for chunk in chunks)
        assert all(any(chunk.char_start <= match.start() and chunk.char_end >= match.end() for chunk in chunks)
                   for match in re.finditer(r"\S+", text))
        for previous, current in zip(chunks, chunks[1:]):
            assert current.char_start > previous.char_start
            shared = text[current.char_start:previous.char_end] if current.char_start < previous.char_end else ""
            assert len(shared.split()) <= overlap


def test_non_whitespace_word_without_tokens_is_rejected():
    class EmptyTokenizer:
        def encode(self, text, *, add_special_tokens, truncation):
            return [0, 1] if add_special_tokens else []

    with pytest.raises(ChunkingError, match="no model tokens"):
        TokenAwareChunker(EmptyTokenizer()).split_page("text", 0)
