from app.models.schemas import NamePair
from app.services.extraction_service import ExtractionPipeline
from tests.fakes import FakeOcr, page_from_lines


class StubNer:
    """Returns whatever it is given, so we can feed names that are not on the page."""

    def __init__(self, names):
        self.names = names

    def person_names(self, text):
        return self.names


def make(names, min_tokens=2):
    ocr = FakeOcr([page_from_lines(0, ["Report by Ana Ruiz for Atlas"])])
    return ExtractionPipeline(ocr, StubNer(names), 0.9, 0.8, min_tokens)


def test_name_ner_found_but_not_on_page_is_skipped_not_crashed(caplog):
    result = make(["Ana Ruiz", "Ghost Person"]).run(b"pdf", [])
    assert [e.name for e in result.extracted_names] == ["Ana Ruiz"]
    assert "not located" in caplog.text


def test_single_token_names_are_dropped_by_default():
    result = make(["Ana Ruiz", "Atlas"]).run(b"pdf", [])
    assert [e.name for e in result.extracted_names] == ["Ana Ruiz"]


def test_single_token_names_allowed_when_configured():
    result = make(["Ana Ruiz", "Atlas"], min_tokens=1).run(b"pdf", [])
    assert {e.name for e in result.extracted_names} == {"Ana Ruiz", "Atlas"}


def test_fuzzy_matches_only_use_located_names():
    result = make(["Ana Ruiz", "Ghost Person"]).run(
        b"pdf", [NamePair(first_name="Ghost", last_name="Person")]
    )
    assert result.fuzzy_matches == []
