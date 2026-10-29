"""Box self-check eval (TRD §1, §11): does every returned box really contain its name?

Runs the real ``ExtractNames`` on each sample, then for every occurrence renders just
that box (plus a small margin) at high DPI, OCRs the crop as a single line and
fuzzy-compares it with the reported name. Also measures occurrence recall against
``tests/golden/persons.json``. Exits 1 unless 100 % of boxes pass and recall ≥ 0.95.

Usage: ``uv run python scripts/eval_boxes.py``
"""

import io
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image
from rapidfuzz import fuzz

from app.application.extract_names import ExtractNames
from app.domain.names import normalize_name
from app.domain.persons import NameOccurrence
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.settings import load_settings
from app.infrastructure.spacy_recognizer import SpacyPersonNameRecognizer
from app.infrastructure.tesseract_ocr import TesseractOcrEngine

ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests" / "golden" / "persons.json"
SAMPLES = ROOT / "sample_pdfs"
CROP_DPI = 300
CROP_MARGIN_PT = 2.0
SINGLE_LINE = "--psm 7"
MIN_BOX_SCORE = 90
MIN_RECALL = 0.95


def main() -> int:
    settings = load_settings()
    rasterizer = PyMuPdfRasterizer()
    ocr = TesseractOcrEngine(
        settings.ocr_languages,
        settings.ocr_confidence_floor,
        settings.ocr_timeout_seconds,
        settings.tesseract_cmd,
    )
    extract = ExtractNames(
        rasterizer,
        ocr,
        SpacyPersonNameRecognizer(settings.ner_model),
        settings.render_dpi,
        settings.fuzzy_threshold,
    )
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    expected_by_page = {
        (p["document"], p["page"]): Counter(normalize_name(n) for n in p["persons"])
        for p in golden["pages"]
    }

    checked = passed = located = expected_total = 0
    failures: list[str] = []
    for document in sorted({doc for doc, _ in expected_by_page}):
        pdf = (SAMPLES / document).read_bytes()
        occurrences = extract.execute(pdf, []).occurrences
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            for occurrence in occurrences:
                checked += 1
                read, score = _recheck(doc, occurrence)
                if score >= MIN_BOX_SCORE:
                    passed += 1
                else:
                    failures.append(
                        f"{document} p{occurrence.page_index}: {occurrence.name!r} "
                        f"read as {read!r} (score {score:.0f})"
                    )
        for (doc_name, page_index), expected in expected_by_page.items():
            if doc_name != document:
                continue
            found = Counter(
                normalize_name(o.name) for o in occurrences if o.page_index == page_index
            )
            located += sum((found & expected).values())
            expected_total += expected.total()

    pass_rate = passed / checked if checked else 0.0
    recall = located / expected_total if expected_total else 0.0
    print(f"Box self-check — {checked} boxes, crop at {CROP_DPI} DPI")
    print(f"  boxes re-read as their name: {passed}/{checked} = {pass_rate:.3f} (need 1.000)")
    print(f"  occurrence recall: {located}/{expected_total} = {recall:.3f} (need {MIN_RECALL})")
    for failure in failures:
        print(f"    FAIL {failure}")
    ok = passed == checked and recall >= MIN_RECALL
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def _recheck(doc: pymupdf.Document, occurrence: NameOccurrence) -> tuple[str, float]:
    """OCR the box's crop and score it against the reported name (0..100)."""
    box = occurrence.box
    clip = pymupdf.Rect(
        box.x - CROP_MARGIN_PT,
        box.y - CROP_MARGIN_PT,
        box.right + CROP_MARGIN_PT,
        box.bottom + CROP_MARGIN_PT,
    )
    pixmap = doc[occurrence.page_index].get_pixmap(dpi=CROP_DPI, clip=clip)
    with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
        read = pytesseract.image_to_string(image, config=SINGLE_LINE).strip()
    return read, fuzz.ratio(normalize_name(read), normalize_name(occurrence.name))


if __name__ == "__main__":
    sys.exit(main())
