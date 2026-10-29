"""NER eval (TRD §11, spike S1): precision/recall of PERSON recognition on the samples.

OCRs every sample page exactly as the service does (same rasterizer, OCR and page text),
runs the recognizer and compares with ``tests/golden/persons.json`` as per-page multisets
of normalized names. Exits 1 if precision or recall < 0.90 or any golden negative appears.

Usage: ``uv run python scripts/eval_ner.py [--model en_core_web_sm]``
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from app.application.extract_names import read_pages
from app.domain.names import normalize_name
from app.domain.page_text import build_page_text
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.settings import load_settings
from app.infrastructure.spacy_recognizer import SpacyPersonNameRecognizer
from app.infrastructure.tesseract_ocr import TesseractOcrEngine

ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests" / "golden" / "persons.json"
SAMPLES = ROOT / "sample_pdfs"
MIN_PRECISION = 0.90
MIN_RECALL = 0.90


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="spaCy model (default: DOCINTEL_NER_MODEL)")
    args = parser.parse_args()

    settings = load_settings()
    model = args.model or settings.ner_model
    rasterizer = PyMuPdfRasterizer()
    ocr = TesseractOcrEngine(
        settings.ocr_languages,
        settings.ocr_confidence_floor,
        settings.ocr_timeout_seconds,
        settings.tesseract_cmd,
    )
    recognizer = SpacyPersonNameRecognizer(model)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    negatives = {normalize_name(n) for n in golden["negatives"]}

    expected_by_page = {
        (p["document"], p["page"]): Counter(normalize_name(n) for n in p["persons"])
        for p in golden["pages"]
    }
    totals = Counter[str]()
    false_positives: list[str] = []
    false_negatives: list[str] = []
    negatives_hit: list[str] = []
    per_document: dict[str, Counter[str]] = {}

    for document in sorted({doc for doc, _ in expected_by_page}):
        pdf = (SAMPLES / document).read_bytes()
        stats = per_document.setdefault(document, Counter())
        for page in read_pages(rasterizer, ocr, pdf, settings.render_dpi):
            predicted = Counter(
                normalize_name(span.text)
                for span in recognizer.recognize(build_page_text(page).text)
            )
            expected = expected_by_page.get((document, page.index), Counter())
            tp = sum((predicted & expected).values())
            stats.update(tp=tp, predicted=predicted.total(), expected=expected.total())
            where = f"{document} p{page.index}"
            false_positives += [f"{where}: {n}" for n in (predicted - expected).elements()]
            false_negatives += [f"{where}: {n}" for n in (expected - predicted).elements()]
            negatives_hit += [f"{where}: {n}" for n in predicted if n in negatives]
        totals.update(stats)

    print(f"NER eval — model {model}, {settings.render_dpi} DPI")
    for document, stats in per_document.items():
        print(f"  {document:<22} {_metrics(stats)}")
    print(f"  {'TOTAL':<22} {_metrics(totals)}")
    _listing("False positives", false_positives)
    _listing("False negatives", false_negatives)
    _listing("Golden negatives reported as persons", negatives_hit)

    precision, recall = (
        _ratio(totals["tp"], totals["predicted"]),
        _ratio(totals["tp"], totals["expected"]),
    )
    passed = precision >= MIN_PRECISION and recall >= MIN_RECALL and not negatives_hit
    print("PASS" if passed else f"FAIL (need P and R >= {MIN_PRECISION:.2f}, no negatives)")
    return 0 if passed else 1


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _metrics(stats: Counter[str]) -> str:
    precision = _ratio(stats["tp"], stats["predicted"])
    recall = _ratio(stats["tp"], stats["expected"])
    return (
        f"P={precision:.3f} R={recall:.3f} "
        f"(tp={stats['tp']} predicted={stats['predicted']} expected={stats['expected']})"
    )


def _listing(title: str, items: list[str]) -> None:
    print(f"{title}: {len(items)}")
    for item in items:
        print(f"    {item}")


if __name__ == "__main__":
    sys.exit(main())
