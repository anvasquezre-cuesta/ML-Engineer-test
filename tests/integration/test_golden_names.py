"""The real OCR + NER pipeline against the 55 hand-labelled mentions in sample_pdfs/.

Compares, per document, the multiset of (page, name): every labelled mention must
be found on its page (recall) and nothing else may be reported (precision).
"""

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from app.adapters.spacy_ner import SpacyNER
from app.domain.models import OcrPage
from app.services.names import NameExtractor
from tests.integration.conftest import requires_spacy_model, requires_tesseract

pytestmark = [pytest.mark.integration, requires_tesseract, requires_spacy_model]

EXPECTED = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "expected_names.json").read_text(encoding="utf-8")
)


def _key(page: int, name: str) -> tuple[int, str]:
    return page, name.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")  # typographic in the scans


@pytest.mark.parametrize("filename", sorted(EXPECTED["documents"]))
def test_golden_names_on_sample_pdfs(
    filename: str, ocr_sample: Callable[[str], list[OcrPage]], spacy_ner: SpacyNER
) -> None:
    pages = ocr_sample(filename)
    mentions = NameExtractor(spacy_ner).extract(pages)

    found = Counter(_key(m.page, m.name) for m in mentions)
    expected = Counter(
        _key(m["page"], m["name"]) for m in EXPECTED["documents"][filename]["mentions"]
    )
    assert found - expected == Counter(), "false positives"
    assert expected - found == Counter(), "missed mentions"

    for mention in mentions:
        page = pages[mention.page]
        assert 0 <= mention.box.x0 < mention.box.x1 <= page.width_pt
        assert 0 <= mention.box.y0 < mention.box.y1 <= page.height_pt
