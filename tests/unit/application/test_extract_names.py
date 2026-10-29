import json
import logging

import pytest

from app.application.extract_names import ExtractNames
from app.domain.geometry import union_box
from app.domain.name_matching import RequestedName
from tests.fakes import FakeOcrEngine, FakeRasterizer, FakeRecognizer, line_of_words

PAGE_0 = line_of_words(1, "From: Margaret Thompson, CEO") + line_of_words(2, "Robert Chen joined")
PAGE_1 = line_of_words(1, "Approved by Margaret Thompson")


def _use_case(
    ocr: FakeOcrEngine | None = None, recognizer: FakeRecognizer | None = None
) -> ExtractNames:
    return ExtractNames(
        rasterizer=FakeRasterizer(pages=2),
        ocr=ocr or FakeOcrEngine({0: PAGE_0, 1: PAGE_1}),
        recognizer=recognizer or FakeRecognizer(["Margaret Thompson", "Robert Chen"]),
        dpi=300,
        fuzzy_threshold=0.90,
    )


def test_occurrences_on_both_pages_in_order() -> None:
    ocr = FakeOcrEngine({0: PAGE_0, 1: PAGE_1})

    result = _use_case(ocr=ocr).execute(b"%PDF-", [])

    assert ocr.calls == [0, 1]
    assert result.page_count == 2
    assert [(o.name, o.page_index) for o in result.occurrences] == [
        ("Margaret Thompson", 0),
        ("Robert Chen", 0),
        ("Margaret Thompson", 1),
    ]
    assert result.occurrences[0].box == union_box([PAGE_0[1].box, PAGE_0[2].box])


def test_unique_names_are_matched_against_the_request() -> None:
    result = _use_case().execute(
        b"%PDF-", [RequestedName("Margaret", "Thompson"), RequestedName("Ana", "Lopez")]
    )

    assert [(m.extracted_name, m.matched_name, m.score) for m in result.matches] == [
        ("Margaret Thompson", "Margaret Thompson", 1.0)
    ]


def test_no_requested_names_means_no_matches() -> None:
    assert _use_case().execute(b"%PDF-", []).matches == ()


def test_recognizer_runs_once_per_page() -> None:
    recognizer = FakeRecognizer(["Robert Chen"])

    _use_case(recognizer=recognizer).execute(b"%PDF-", [])

    assert recognizer.calls == 2


def test_completion_log_has_counts_and_hash_but_no_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    _use_case().execute(b"%PDF-", [RequestedName("Margaret", "Thompson")])

    (record,) = [r for r in caplog.records if r.getMessage() == "extraction_completed"]
    fields = vars(record)
    assert fields["page_count"] == 2
    assert fields["occurrence_count"] == 3
    assert fields["unique_name_count"] == 2
    assert fields["match_count"] == 1
    assert len(fields["document_sha256"]) == 12
    assert {"ocr_ms", "ner_ms", "align_ms", "match_ms"} <= fields.keys()
    serialized = json.dumps(fields, default=str)
    assert "Margaret" not in serialized
    assert "Robert" not in serialized
