"""Real OCR and spaCy regression for an OCR bullet that created false ambiguity."""

import os
from pathlib import Path

from app.core.config import Settings
from app.services.extraction_service import ExtractionService
from app.services.fuzzy_service import normalize_name
from app.services.ner_service import SpacyPersonRecognizer
from app.services.ocr_service import OCRService


def test_real_sample_recovers_the_bulleted_and_nonbulleted_occurrences():
    sample = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))
    settings = Settings()
    document = OCRService(settings).extract_file(sample / "meeting_minutes.pdf")
    recognizer = SpacyPersonRecognizer.load(settings.ner_model, settings.ner_max_page_chars)
    spans = recognizer.detect_pages(tuple(page.text for page in document.pages))
    baseline = ExtractionService(None, None, Settings(ner_name_recovery_passes=0))._assemble(document, spans, [])
    recovered = ExtractionService(None, None, Settings(ner_name_recovery_passes=1))._assemble(document, spans, [])
    original_names = [item for item in baseline.extracted_names if normalize_name(item.name) == "elizabeth park"]
    located = [item for item in recovered.extracted_names if normalize_name(item.name) == "elizabeth park"]
    assert len(original_names) == 1 and len(located) == 3
    assert all(item.bounding_box.page_number == 0 for item in located)
    assert len({(item.bounding_box.x, item.bounding_box.y) for item in located}) == 3
