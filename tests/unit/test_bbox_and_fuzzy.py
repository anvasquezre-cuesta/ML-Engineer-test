from dataclasses import replace

import pytest

from app.models.document import OCRPage, OCRWord, WordBox
from app.models.extraction import PersonSpan
from app.models.schemas import NamePair
from app.services.bbox_service import find_name_bounding_boxes, locate_person_span
from app.services.fuzzy_service import match_names, normalize_name


def word(text, start, x, y=10, *, block=1, paragraph=1, line=1, width=20, height=10):
    return OCRWord(text, WordBox(x, y, width, height), start, start + len(text), block, paragraph, line, 90)


def page(text, words, number=0):
    return OCRPage(number, 500, 500, text, tuple(words))


def test_encloses_a_name_and_preserves_page_number():
    source = page("Alice Smith", [word("Alice", 0, 10, width=30), word("Smith", 6, 45, width=25)], 2)
    result = locate_person_span(source, PersonSpan("Alice Smith", 0, 11))
    assert result.name == "Alice Smith"
    assert result.bounding_box.model_dump() == {"page_number": 2, "x": 10.0, "y": 10.0, "width": 60.0, "height": 10.0}


def test_repeated_names_are_located_by_occurrence_not_global_search():
    source = page("Jane Doe Jane Doe", [
        word("Jane", 0, 10), word("Doe", 5, 35), word("Jane", 9, 100), word("Doe", 14, 125),
    ])
    first = locate_person_span(source, PersonSpan("Jane Doe", 0, 8))
    second = locate_person_span(source, PersonSpan("Jane Doe", 9, 17))
    assert first.bounding_box.x == 10
    assert second.bounding_box.x == 100


def test_adjacent_lines_in_same_block_are_enclosed():
    source = page("Alice\nSmith", [word("Alice", 0, 40), word("Smith", 6, 10, y=22, line=2)])
    box = locate_person_span(source, PersonSpan("Alice\nSmith", 0, 11)).bounding_box
    assert (box.x, box.y, box.width, box.height) == (10, 10, 50, 22)


def test_partial_ocr_word_uses_its_whole_box():
    source = page("(Alice)", [word("(Alice)", 0, 10, width=30)])
    assert locate_person_span(source, PersonSpan("Alice", 1, 6)).bounding_box.width == 30


@pytest.mark.parametrize("words", [
    [word("Alice", 0, 10), word("Smith", 6, 300)],
    [word("Alice", 0, 10), word("Smith", 6, 35, block=2)],
    [word("Alice", 0, 10), word("Smith", 6, 35, paragraph=2)],
    [word("Alice", 0, 10), word("Smith", 6, 10, y=22, line=3)],
    [word("Alice", 0, 10), word("Smith", 6, 10, y=100, line=2)],
    [word("Alice", 0, 10), word("Smith", 6, float("nan"))],
])
def test_rejects_unrelated_or_invalid_boxes(words):
    assert locate_person_span(page("Alice Smith", words), PersonSpan("Alice Smith", 0, 11)) is None


def test_rejects_wrong_offsets_or_uncovered_non_whitespace():
    source = page("Alice X Smith", [word("Alice", 0, 10), word("Smith", 8, 35)])
    assert locate_person_span(source, PersonSpan("Alice X Smith", 0, 13)) is None
    assert locate_person_span(source, PersonSpan("Alice Smith", 0, 11)) is None
    assert locate_person_span(page("Alice", []), PersonSpan("Alice", 0, 5)) is None


def test_rejects_inconsistent_ocr_word_offsets():
    source = page("Alice Smith", [word("Alice", 0, 10), replace(word("Smith", 6, 35), char_end=10)])
    assert locate_person_span(source, PersonSpan("Alice Smith", 0, 11)) is None


def test_legacy_bbox_helper_handles_case_ocr_noise_and_occurrences(monkeypatch):
    from app.models.document import OCRDocument

    source = page("Alice Smith A1ice Smith", [
        word("Alice", 0, 10), word("Smith", 6, 35), word("A1ice", 12, 100), word("Smith", 18, 125),
    ])
    monkeypatch.setattr("app.services.ocr_service.OCRService.extract_file", lambda self, path: OCRDocument((source,)))
    result = find_name_bounding_boxes("unused.pdf", "ALICE SMITH")
    assert [item["name"] for item in result] == ["Alice Smith", "A1ice Smith"]
    assert [item["x"] for item in result] == [10, 100]


def test_normalization_accents_case_spaces_and_punctuation():
    assert normalize_name("  MARÍA  González ") == "maria gonzalez"
    assert normalize_name("Anne-Marie O’Brien") == "anne marie obrien"
    assert normalize_name(" Anne Maria O'Brien ") == "anne maria obrien"


def test_fuzzy_matches_full_names_and_preserves_originals():
    result = match_names(
        ["María González", "María González", "John"],
        [NamePair(first_name="Maria", last_name="Gonzalez"), NamePair(first_name="John", last_name="Smith")],
        0.90,
    )
    assert [item.model_dump() for item in result] == [
        {"extracted_name": "María González", "matched_name": "Maria Gonzalez", "score": 1.0}
    ]


def test_fuzzy_threshold_is_inclusive_and_scores_are_normalized(monkeypatch):
    monkeypatch.setattr("app.services.fuzzy_service.fuzz.ratio", lambda *_: 90)
    names = [NamePair(first_name="Ana", last_name="Doe")]
    assert match_names(["Ana Doe"], names, 0.90)[0].score == 0.9
    assert match_names(["Ana Doe"], names, 0.91) == []


def test_fuzzy_empty_and_invalid_threshold():
    assert match_names([], [NamePair(first_name="A", last_name="B")], 0.9) == []
    assert match_names(["---"], [NamePair(first_name="A", last_name="B")], 0.0) == []
    with pytest.raises(ValueError):
        match_names([], [], float("nan"))
