"""Page text assembly: NER offsets must map back to the exact OCR words."""

from hypothesis import given
from hypothesis import strategies as st
import pytest

from app.domain.page_text import build_page_text
from tests.builders import page_words

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="page text not built yet"
)

tokens = st.text(
    alphabet=st.characters(categories=["L", "N", "P"]), min_size=1, max_size=8
)
lines = st.lists(tokens, min_size=1, max_size=4).map(" ".join)
blocks = st.lists(
    st.lists(lines, min_size=1, max_size=3), min_size=1, max_size=3
)


@given(blocks)
def test_offsets_slice_back_to_words_and_gaps_mark_the_layout(
    layout: list[list[str]],
) -> None:
    page = page_words(layout)

    text = build_page_text(page)

    assert [text.text[w.start : w.end] for w in text.words] == [
        w.text for w in page.words
    ]
    assert text.words[0].start == 0
    assert text.words[-1].end == len(text.text)
    for before, after in zip(text.words, text.words[1:], strict=False):
        gap = text.text[before.end : after.start]
        if after.word.block != before.word.block:
            assert gap == "\n\n"
        elif after.word.line != before.word.line:
            assert gap == "\n"
        else:
            assert gap == " "
