import random

import pytest

from app.domain.chunking import Chunk, chunk_document, document_id_for
from app.domain.document import Page, Word
from app.domain.geometry import BoundingBox

SEEDS = range(200)
VOCABULARY = ("the", "board", "approved", "Dr.", "Foster", "costs.", "why?", "yes!", "Q3", "2024")


def count_words(text: str) -> int:
    return len(text.split())


def _word(text: str, block: int, line: int) -> Word:
    return Word(text, BoundingBox(0, line * 20, 10, 10), 95.0, (block, 1, line))


def _block(block: int, lines: list[list[str]], first_line: int = 1) -> list[Word]:
    return [
        _word(text, block, first_line + offset)
        for offset, line in enumerate(lines)
        for text in line
    ]


def _page(index: int, words: list[Word]) -> Page:
    return Page(index, 612, 792, tuple(words))


def _chunk(pages: list[Page], max_tokens: int) -> tuple[Chunk, ...]:
    return chunk_document(pages, "doc", "memo.pdf", max_tokens, count_words)


def _random_document(rng: random.Random) -> list[Page]:
    pages = []
    for index in range(rng.randint(1, 3)):
        words: list[Word] = []
        line = 1
        for block in range(1, rng.randint(0, 6) + 1):
            for _ in range(rng.randint(1, 4)):
                texts = [rng.choice(VOCABULARY) for _ in range(rng.randint(1, 12))]
                words += [_word(text, block, line) for text in texts]
                line += 1
        pages.append(_page(index, words))
    return pages


@pytest.mark.parametrize("seed", SEEDS)
def test_no_word_is_lost_duplicated_or_cut(seed: int) -> None:
    rng = random.Random(seed)
    pages = _random_document(rng)

    chunks = _chunk(pages, rng.randint(1, 60))

    ocr_words = [word.text for page in pages for word in page.words]
    assert [token for chunk in chunks for token in chunk.text.split()] == ocr_words
    for chunk in chunks:
        assert chunk.text == chunk.text.strip()


@pytest.mark.parametrize("seed", SEEDS)
def test_every_chunk_respects_the_budget_unless_it_is_one_word(seed: int) -> None:
    rng = random.Random(seed)
    budget = rng.randint(1, 60)

    chunks = _chunk(_random_document(rng), budget)

    for chunk in chunks:
        assert count_words(chunk.text) <= budget or count_words(chunk.text) == 1


@pytest.mark.parametrize("seed", SEEDS)
def test_chunks_never_span_pages_and_are_numbered_in_order(seed: int) -> None:
    rng = random.Random(seed)
    pages = _random_document(rng)

    chunks = _chunk(pages, rng.randint(1, 60))

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert [chunk.page for chunk in chunks] == sorted(chunk.page for chunk in chunks)
    for chunk in chunks:
        page_words = {word.text for word in pages[chunk.page].words}
        assert set(chunk.text.split()) <= page_words


def test_one_chunk_per_page_with_exact_metadata() -> None:
    pages = [
        _page(0, _block(1, [["Margaret", "Thompson"]])),
        _page(1, _block(1, [["Richard", "Hernandez"]])),
    ]

    chunks = _chunk(pages, 1000)

    assert [(c.page, c.chunk_index, c.text) for c in chunks] == [
        (0, 0, "Margaret Thompson"),
        (1, 1, "Richard Hernandez"),
    ]
    assert {(c.document_id, c.file_name) for c in chunks} == {("doc", "memo.pdf")}


def test_whole_paragraphs_are_packed_and_the_one_that_does_not_fit_moves_whole() -> None:
    blocks = [_block(n, [[f"b{n}"] * 40], first_line=n) for n in (1, 2, 3)]

    chunks = _chunk([_page(0, blocks[0] + blocks[1] + blocks[2])], 100)

    assert [count_words(c.text) for c in chunks] == [80, 40]
    assert chunks[0].text == " ".join(["b1"] * 40) + "\n" + " ".join(["b2"] * 40)
    assert chunks[1].text == " ".join(["b3"] * 40)


def test_oversized_paragraph_is_split_only_between_sentences() -> None:
    sentence_lengths = (100, 120, 90, 90)
    words: list[str] = []
    for number, length in enumerate(sentence_lengths, start=1):
        body = [f"s{number}"] * (length - 1)
        if number == 1:
            body[10:12] = ["Dr.", "Foster"]
        words += [*body, f"end{number}."]
    # 30 words per line: line breaks fall in the middle of every sentence.
    lines = [words[i : i + 30] for i in range(0, len(words), 30)]

    chunks = _chunk([_page(0, _block(1, lines))], 250)

    assert [count_words(c.text) for c in chunks] == [220, 180]
    assert chunks[0].text.endswith("end2.")
    assert chunks[1].text.startswith("s3")
    assert chunks[1].text.endswith("end4.")


def test_honorific_is_not_a_sentence_end() -> None:
    # If "Dr." ended a sentence, chunk 1 could take "s1 … Dr." (200 + 40 words ≤ 250).
    paragraph_a = _block(1, [["a"] * 199 + ["enda."]])
    first_sentence = ["s1"] * 39 + ["Dr."] + ["s1"] * 59 + ["end1."]
    second_sentence = ["s2"] * 199 + ["end2."]
    paragraph_b = _block(2, [first_sentence, second_sentence], first_line=2)

    chunks = _chunk([_page(0, paragraph_a + paragraph_b)], 250)

    assert [count_words(c.text) for c in chunks] == [200, 100, 200]
    assert chunks[1].text.startswith("s1") and chunks[1].text.endswith("end1.")


def test_oversized_sentence_is_split_between_words() -> None:
    chunks = _chunk([_page(0, _block(1, [["word"] * 7]))], 3)

    assert [c.text for c in chunks] == ["word word word", "word word word", "word"]


def test_word_over_budget_becomes_its_own_chunk() -> None:
    def count_characters(text: str) -> int:
        return len(text)

    page = _page(0, _block(1, [["a", "extraordinarily", "b"]]))

    chunks = chunk_document([page], "doc", "memo.pdf", 5, count_characters)

    assert [c.text for c in chunks] == ["a", "extraordinarily", "b"]


def test_line_breaks_inside_a_paragraph_are_kept_but_never_split_points() -> None:
    page = _page(0, _block(1, [["Dr.", "Foster", "said"], ["hello."]]))

    chunks = _chunk([page], 10)

    assert [c.text for c in chunks] == ["Dr. Foster said\nhello."]


def test_empty_pages_add_no_chunk_and_numbering_stays_consecutive() -> None:
    pages = [_page(0, _block(1, [["a"]])), _page(1, []), _page(2, _block(1, [["b"]]))]

    chunks = _chunk(pages, 10)

    assert [(c.page, c.chunk_index) for c in chunks] == [(0, 0), (2, 1)]


def test_document_without_words_has_no_chunks() -> None:
    assert _chunk([_page(0, []), _page(1, [])], 10) == ()


def test_budget_below_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        _chunk([_page(0, _block(1, [["a"]]))], 0)


def test_chunk_id_and_source_formats() -> None:
    chunk = Chunk("972f1893d5c9db06", "company_memo.pdf", 0, 3, "text")

    assert chunk.id == "972f1893d5c9db06:3"
    assert chunk.source == "company_memo.pdf, page 0"


@pytest.mark.parametrize(
    ("page", "chunk_index", "text"), [(-1, 0, "text"), (0, -1, "text"), (0, 0, " ")]
)
def test_invalid_chunk_is_rejected(page: int, chunk_index: int, text: str) -> None:
    with pytest.raises(ValueError):
        Chunk("doc", "memo.pdf", page, chunk_index, text)


def test_document_id_is_a_stable_content_hash_prefix() -> None:
    first = document_id_for(b"%PDF-1.7 A")

    assert first == document_id_for(b"%PDF-1.7 A")
    assert first != document_id_for(b"%PDF-1.7 B")
    assert len(first) == 16
    assert int(first, 16) >= 0
