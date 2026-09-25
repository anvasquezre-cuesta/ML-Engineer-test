"""Sentence chunker: exact page slices that never cut or lose a word."""

import re

import hypothesis
from hypothesis import strategies as st

from app.adapters.text_chunker import sentence
from app.domain import rag

CHUNK_SIZE = 60
CHUNK_OVERLAP = 12

letters = st.characters(min_codepoint=ord("a"), max_codepoint=ord("e"))
words = st.text(alphabet=letters, min_size=1, max_size=9)
oversized = st.text(alphabet=letters, min_size=CHUNK_SIZE + 1, max_size=90)
sentences = st.lists(
    st.one_of(words, words, words, oversized), min_size=1, max_size=8
).map(lambda tokens: " ".join(tokens) + ".")
repeated = st.sampled_from(["The board met.", "HEADER - ACME CORP"])
lines = st.lists(st.one_of(sentences, repeated), min_size=1, max_size=4).map(
    " ".join
)
paragraphs = st.lists(lines, min_size=1, max_size=4).map("\n".join)
pages = st.lists(paragraphs, min_size=0, max_size=5).map("\n\n".join)


@hypothesis.given(pages)
def test_chunks_are_exact_word_safe_slices_covering_the_page(text: str) -> None:
    page = rag.SourcePage(
        document_key="memo.pdf", content_hash="a" * 64, page_number=3, text=text
    )

    chunks = sentence.SentenceTextChunker(CHUNK_SIZE, CHUNK_OVERLAP).split(page)

    for index, chunk in enumerate(chunks):
        assert text[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.text.strip() == chunk.text != ""
        assert chunk.start_char == 0 or text[chunk.start_char - 1].isspace()
        assert chunk.end_char == len(text) or text[chunk.end_char].isspace()
        assert len(chunk.text) <= CHUNK_SIZE or len(chunk.text.split()) == 1
        assert (chunk.document_key, chunk.content_hash) == (
            "memo.pdf",
            "a" * 64,
        )
        assert (chunk.page_number, chunk.chunk_index) == (3, index)
    starts = [chunk.start_char for chunk in chunks]
    assert starts == sorted(set(starts))
    for word in re.finditer(r"\S+", text):
        assert any(
            c.start_char <= word.start() and word.end() <= c.end_char
            for c in chunks
        ), f"word {word.group()!r} at {word.start()} is in no chunk"
