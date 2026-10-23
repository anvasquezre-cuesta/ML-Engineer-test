import pytest
from structlog.testing import capture_logs

from app.domain.models import Box, EntitySpan
from app.services.names import (
    NameExtractor,
    build_line,
    clean_entity,
    group_lines,
    has_fewer_than_two_tokens,
    is_all_caps,
    words_in_span,
)
from tests.fakes import FakeNER, ocr_page, words_on_line


def test_build_line_records_each_words_character_range() -> None:
    line = build_line(0, words_on_line("Dr. Aisha Patel,", line=1))

    assert line.text == "Dr. Aisha Patel,"
    assert line.spans == ((0, 3), (4, 9), (10, 16))


def test_group_lines_splits_by_tesseract_line_and_keeps_order() -> None:
    page = ocr_page(0, words_on_line("MEETING MINUTES", line=1), words_on_line("Date: 2024", 2))

    assert [line.text for line in group_lines(page)] == ["MEETING MINUTES", "Date: 2024"]


def test_entity_box_merges_overlapping_words_and_excludes_title() -> None:
    page = ocr_page(0, words_on_line("Dr. Aisha Patel, Independent Director", line=1))

    (mention,) = NameExtractor(FakeNER("Aisha Patel")).extract([page])

    aisha, patel = page.words[1], page.words[2]
    assert mention.name == "Aisha Patel"
    assert mention.box == Box(aisha.box.x0, aisha.box.y0, patel.box.x1, patel.box.y1)


def test_title_inside_the_entity_is_stripped_from_name_and_box() -> None:
    # A model that does include the title must still give a box without it.
    page = ocr_page(0, words_on_line("Lead: Prof. Michael O'Sullivan", line=1))

    (mention,) = NameExtractor(FakeNER("Prof. Michael O'Sullivan")).extract([page])

    assert mention.name == "Michael O'Sullivan"
    assert mention.box.x0 == page.words[2].box.x0  # starts at "Michael", not "Prof."


def test_hyphenated_surname_is_one_word_in_one_box() -> None:
    page = ocr_page(0, words_on_line("Lead: Dr. Fatima Al-Rashidi", line=1))

    (mention,) = NameExtractor(FakeNER("Fatima Al-Rashidi")).extract([page])

    fatima, rashidi = page.words[2], page.words[3]
    assert mention.box == Box(fatima.box.x0, fatima.box.y0, rashidi.box.x1, rashidi.box.y1)


def test_partial_overlap_selects_the_whole_ocr_word() -> None:
    line = build_line(0, words_on_line("(PI: Dr. Benjamin Foster): $600K", line=1))

    words = words_in_span(line, line.text.index("Benjamin"), line.text.index("):"))

    assert [w.text for w in words] == ["Benjamin", "Foster):"]


def test_overlap_test_excludes_words_that_only_touch_the_span() -> None:
    line = build_line(0, words_on_line("Kevin O'Brien noted", line=1))

    words = words_in_span(line, 0, len("Kevin O'Brien"))  # ends right before the space

    assert [w.text for w in words] == ["Kevin", "O'Brien"]


def test_every_occurrence_is_returned_with_its_own_page_and_box() -> None:
    pages = [
        ocr_page(0, words_on_line("Richard Hernandez, Chairman", 1)),
        ocr_page(1, words_on_line("Notes", 1), words_on_line("Richard Hernandez adjourned", 2)),
    ]

    mentions = NameExtractor(FakeNER("Richard Hernandez")).extract(pages)

    assert [(m.name, m.page) for m in mentions] == [
        ("Richard Hernandez", 0),
        ("Richard Hernandez", 1),
    ]
    assert mentions[0].box.y0 != mentions[1].box.y0  # different lines on different pages


def test_all_caps_heading_is_not_a_person() -> None:
    page = ocr_page(0, words_on_line("BOARD OF DIRECTORS - MEETING MINUTES", line=1))

    assert NameExtractor(FakeNER("MEETING MINUTES")).extract([page]) == []


def test_single_token_entity_is_rejected() -> None:
    page = ocr_page(0, words_on_line("codenamed 'Atlas' will be managed", line=1))

    assert NameExtractor(FakeNER("Atlas")).extract([page]) == []


def test_filters_can_be_switched_off() -> None:
    page = ocr_page(0, words_on_line("codenamed Atlas", line=1))

    (mention,) = NameExtractor(FakeNER("Atlas"), filters=()).extract([page])

    assert mention.name == "Atlas"


def test_confidence_is_the_mean_of_the_names_words() -> None:
    page = ocr_page(0, words_on_line("From: Margaret Thompson,", line=1, conf=[99.0, 90.0, 80.0]))

    (mention,) = NameExtractor(FakeNER("Margaret Thompson")).extract([page])

    assert mention.confidence == pytest.approx(85.0)


def test_ner_is_called_once_per_document_with_one_text_per_line() -> None:
    ner = FakeNER("Jennifer Liu")
    pages = [
        ocr_page(0, words_on_line("Jennifer Liu, Secretary", 1), words_on_line("Absent:", 2)),
        ocr_page(1, words_on_line("Jennifer Liu", 1)),
    ]

    NameExtractor(ner).extract(pages)

    assert ner.calls == [["Jennifer Liu, Secretary", "Absent:", "Jennifer Liu"]]


def test_extraction_logs_counts_but_never_names() -> None:
    page = ocr_page(0, words_on_line("Kevin O'Brien noted", line=1))

    with capture_logs() as logs:
        NameExtractor(FakeNER("Kevin O'Brien")).extract([page])

    (done,) = [e for e in logs if e["event"] == "names_extracted"]
    assert (done["names_found"], done["line_count"]) == (1, 1)
    assert "Brien" not in str(logs)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("RESEARCH DEPARTMENT", True), ("Kevin O'Brien", False), ("Raj K", False), ("2024", False)],
)
def test_is_all_caps(name: str, expected: bool) -> None:
    assert is_all_caps(name) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Forbes", True), ("Al-Rashidi", True), ("Anna Kowalski", False)],
)
def test_has_fewer_than_two_tokens(name: str, expected: bool) -> None:
    assert has_fewer_than_two_tokens(name) is expected


@pytest.mark.parametrize(
    ("raw", "start", "cleaned", "cleaned_start"),
    [
        ("Dr. Yuki Tanaka", 10, "Yuki Tanaka", 14),
        ("- Jennifer Liu", 0, "Jennifer Liu", 2),  # list bullet seen on meeting_minutes.pdf
        ("(PI: Dr. Benjamin Foster):", 5, "PI: Dr. Benjamin Foster", 6),
        ("Kevin O'Brien,", 0, "Kevin O'Brien", 0),
        ("- Prof. Hans Weber", 3, "Hans Weber", 11),
    ],
)
def test_clean_entity_trims_text_and_moves_the_range(
    raw: str, start: int, cleaned: str, cleaned_start: int
) -> None:
    result = clean_entity(EntitySpan(raw, start, start + len(raw)))

    assert result.text == cleaned
    assert result.start_char == cleaned_start
    assert result.end_char - result.start_char == len(cleaned)


def test_clean_entity_leaves_clean_names_alone() -> None:
    entity = EntitySpan("Drew Barrymore", 0, 14)  # starts with "Dr" but is not a title

    assert clean_entity(entity) is entity


def test_bullet_inside_the_entity_is_kept_out_of_the_box() -> None:
    page = ocr_page(0, words_on_line("- Jennifer Liu, Secretary", line=1))

    (mention,) = NameExtractor(FakeNER("- Jennifer Liu")).extract([page])

    assert mention.name == "Jennifer Liu"
    assert mention.box.x0 == page.words[1].box.x0  # starts at "Jennifer", not "-"
