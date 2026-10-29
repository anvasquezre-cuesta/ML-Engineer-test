import json
from collections import Counter
from pathlib import Path

from tests.conftest import SAMPLE_PAGE_COUNTS

GOLDEN = json.loads(
    (Path(__file__).parents[1] / "golden" / "persons.json").read_text(encoding="utf-8")
)


def test_golden_set_covers_every_sample_page() -> None:
    pages = {(p["document"], p["page"]) for p in GOLDEN["pages"]}

    assert pages == {
        ("company_memo.pdf", 0),
        ("meeting_minutes.pdf", 0),
        ("meeting_minutes.pdf", 1),
        ("research_report.pdf", 0),
        ("research_report.pdf", 1),
    }


def test_golden_set_has_every_occurrence() -> None:
    occurrences = [name for page in GOLDEN["pages"] for name in page["persons"]]
    minutes = [
        name
        for page in GOLDEN["pages"]
        if page["document"] == "meeting_minutes.pdf"
        for name in page["persons"]
    ]

    assert len(occurrences) == 55
    assert Counter(minutes)["Richard Hernandez"] == 5


def test_golden_set_lists_the_required_negatives() -> None:
    assert {
        "Atlas",
        "NovaTech Solutions",
        "ETH Zurich",
        "Stanford University",
        "London",
        "CTO",
    } <= set(GOLDEN["negatives"])


def test_no_negative_is_also_a_person() -> None:
    persons = {name for page in GOLDEN["pages"] for name in page["persons"]}

    assert persons.isdisjoint(GOLDEN["negatives"])


QUESTIONS = json.loads(
    (Path(__file__).parents[1] / "golden" / "questions.json").read_text(encoding="utf-8")
)["questions"]


def test_golden_questions_have_unique_ids_and_known_kinds() -> None:
    ids = [q["id"] for q in QUESTIONS]

    assert len(ids) == len(set(ids))
    assert {q["kind"] for q in QUESTIONS} == {"answerable", "unanswerable", "injection"}
    assert sum(q["kind"] == "unanswerable" for q in QUESTIONS) >= 2
    assert sum(q["kind"] == "injection" for q in QUESTIONS) == 1


def test_golden_answers_point_at_existing_sample_pages() -> None:
    for question in (q for q in QUESTIONS if q["kind"] == "answerable"):
        assert question["fact"].strip()
        assert question["expected_sources"]
        for source in question["expected_sources"]:
            file_name, page = source.rsplit(", page ", 1)
            assert 0 <= int(page) < SAMPLE_PAGE_COUNTS[file_name], source
