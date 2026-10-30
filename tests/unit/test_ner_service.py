import pytest

from app.config import Settings
from app.services import ner_service
from app.services.ner_service import extract_names, find_person_spans


@pytest.fixture(autouse=True)
def default_settings(monkeypatch):
    monkeypatch.setattr(ner_service, "get_settings", lambda: Settings(_env_file=None))


def test_ac_ner_02_filters_drop_non_names():
    page = "Robert Chen\nCFO Chen JOHN SMITH"
    spans = [("Robert Chen\nCFO", 0, 15), ("Chen", 16, 20), ("JOHN SMITH", 21, 31)]

    assert find_person_spans([page], {page: spans}.get) == [[]]


def test_ac_ner_05_all_caps_kept_when_disabled(monkeypatch):
    keep = Settings(_env_file=None, ner_drop_all_caps=False)
    monkeypatch.setattr(ner_service, "get_settings", lambda: keep)

    result = find_person_spans(["JOHN SMITH"], lambda text: [("JOHN SMITH", 0, 10)])

    assert result == [[("JOHN SMITH", 0, 10)]]


def test_ac_ner_07_extract_names_unique_and_empty(monkeypatch):
    spans = [("Ann Lee", 0, 7), ("Bob Ray", 12, 19), ("Ann Lee", 25, 32)]
    monkeypatch.setattr(ner_service, "spacy_persons", lambda text: spans)

    assert extract_names("Ann Lee met Bob Ray, then Ann Lee") == ["Ann Lee", "Bob Ray"]
    assert find_person_spans([]) == []
    monkeypatch.setattr(ner_service, "spacy_persons", lambda text: [])
    assert extract_names("") == []


def test_ac_ner_03_propagates_to_other_pages():
    pages = ["Robert Chen signed", "Robert Chen and Robert Chen"]
    fake = {pages[0]: [("Robert Chen", 0, 11)], pages[1]: []}.get

    result = find_person_spans(pages, fake)

    assert result[1] == [("Robert Chen", 0, 11), ("Robert Chen", 16, 27)]


def test_ac_ner_04_word_boundaries_and_no_duplicates():
    page = "Ann Lee met Ann Leeds and LeeAnn Lee"

    result = find_person_spans([page], lambda text: [("Ann Lee", 0, 7)])

    assert result == [[("Ann Lee", 0, 7)]]


def test_ac_ner_06_sorted_by_start_and_offsets_match():
    pages = ["Ann Lee met Bob Ray", "Bob Ray met Ann Lee"]
    fake = {pages[0]: [("Bob Ray", 12, 19)], pages[1]: [("Ann Lee", 12, 19)]}.get

    result = find_person_spans(pages, fake)

    assert result[0] == [("Ann Lee", 0, 7), ("Bob Ray", 12, 19)]
    assert all(
        page[s:e] == n
        for page, spans in zip(pages, result, strict=True)
        for n, s, e in spans
    )
