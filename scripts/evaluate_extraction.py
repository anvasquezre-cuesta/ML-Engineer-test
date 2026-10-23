"""Measure name extraction against the 55 hand-labelled mentions in sample_pdfs/.

Prints precision, recall, mean OCR confidence and timings for the current settings
(change them with environment variables, e.g. ``OCR__DPI=150`` or ``NER__MODEL=...``).
The numbers in DECISIONS.md come from this script.

    uv run python scripts/evaluate_extraction.py
    OCR__DPI=150 uv run python scripts/evaluate_extraction.py
    NER__MODEL=en_core_web_sm uv run --with <model wheel URL> python scripts/evaluate_extraction.py
"""

import json
import time
from collections import Counter
from pathlib import Path
from statistics import fmean

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.spacy_ner import SpacyNER
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import get_settings
from app.services.documents import DocumentLoader
from app.services.names import NameExtractor
from app.services.ocr import OcrService

ROOT = Path(__file__).parents[1]
EXPECTED = json.loads((ROOT / "tests/fixtures/expected_names.json").read_text(encoding="utf-8"))


def _key(page: int, name: str) -> tuple[int, str]:
    return page, name.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")


def main() -> None:
    settings = get_settings()
    renderer = PyMuPDFRenderer()
    loader = DocumentLoader(renderer, max_bytes=10**8, max_pages=50)
    ocr = OcrService(renderer, TesseractOCR(settings.ocr), dpi=settings.ocr.dpi)
    extractor = NameExtractor(SpacyNER(settings.ner))

    tp = fp = fn = 0
    errors: list[str] = []
    confidences: list[float] = []
    ocr_s = ner_s = 0.0
    for filename, doc in sorted(EXPECTED["documents"].items()):
        document = loader.load((ROOT / "sample_pdfs" / filename).read_bytes())
        started = time.perf_counter()
        pages = ocr.read(document)
        ocr_s += time.perf_counter() - started
        confidences += [w.confidence for p in pages for w in p.words]

        started = time.perf_counter()
        mentions = extractor.extract(pages)
        ner_s += time.perf_counter() - started

        found = Counter(_key(m.page, m.name) for m in mentions)
        expected = Counter(_key(m["page"], m["name"]) for m in doc["mentions"])
        tp += sum((found & expected).values())
        fp += sum((found - expected).values())
        fn += sum((expected - found).values())
        errors += [f"FP {filename} p{p} {n}" for (p, n) in (found - expected).elements()]
        errors += [f"FN {filename} p{p} {n}" for (p, n) in (expected - found).elements()]

    print(
        f"dpi={settings.ocr.dpi} psm={settings.ocr.psm} ner={settings.ner.model} | "
        f"precision={tp / max(tp + fp, 1):.3f} recall={tp / max(tp + fn, 1):.3f} "
        f"(tp={tp} fp={fp} fn={fn}) | mean_conf={fmean(confidences):.1f} | "
        f"ocr={ocr_s:.1f}s ner={ner_s:.2f}s"
    )
    for error in errors:
        print("  ", ascii(error))


if __name__ == "__main__":
    main()
