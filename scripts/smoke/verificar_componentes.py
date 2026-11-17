"""Check real OCR, NER, bounding boxes and fuzzy matching on the sample PDF."""

import math
from pathlib import Path

from app.core.config import Settings
from app.models.schemas import NamePair
from app.services.bbox_service import PageLocator
from app.services.fuzzy_service import match_names
from app.services.ner_service import SpacyPersonRecognizer
from app.services.ocr_service import OCRService


SAMPLE = Path("/samples/meeting_minutes.pdf")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  [OK] {message}", flush=True)


def main() -> None:
    check(SAMPLE.is_file(), "The sample PDF is available")
    settings = Settings()

    print("\n1. Real OCR: process the PDF", flush=True)
    document = OCRService(settings).extract_file(SAMPLE)
    check(len(document.pages) == 2, "Two pages were processed")
    for number, page in enumerate(document.pages):
        check(page.page_number == number and bool(page.words), f"Page {number} contains OCR words")
        check(
            all(page.text[word.char_start:word.char_end] == word.text for word in page.words),
            f"Word offsets match the text on page {number}",
        )

    print("\n2. Real NER: detect people on each page", flush=True)
    recognizer = SpacyPersonRecognizer.load(settings.ner_model, settings.ner_max_page_chars)
    spans_by_page = [recognizer.detect_page(page.text) for page in document.pages]
    for page, spans in zip(document.pages, spans_by_page, strict=True):
        check(
            all(page.text[span.char_start:span.char_end] == span.text for span in spans),
            f"Spans correspond to the OCR text on page {page.page_number}",
        )

    print("\n3. Real bounding boxes: locate spans using words from the same OCR output", flush=True)
    located = []
    omitted = 0
    for page, spans in zip(document.pages, spans_by_page, strict=True):
        locator = PageLocator(page)
        for span in spans:
            result = locator.locate(span)
            if result is None:
                omitted += 1
                continue
            box = result.bounding_box
            valid = (
                box.page_number == page.page_number
                and all(math.isfinite(value) for value in (box.x, box.y, box.width, box.height))
                and box.x >= 0 and box.y >= 0 and box.width > 0 and box.height > 0
                and box.x + box.width <= page.width + 1e-4
                and box.y + box.height <= page.height + 1e-4
            )
            if not valid:
                raise AssertionError(f"Invalid bounding box on page {page.page_number}")
            located.append(result)
    check(bool(located), "Located bounding boxes are valid and fit within their pages")
    thomas_pages = {
        result.bounding_box.page_number for result in located if result.name == "Thomas Muller"
    }
    check(thomas_pages == {0, 1}, "Thomas Muller is located on pages 0 and 1")

    print("\n4. Real fuzzy matching: compare full names", flush=True)
    queries = [NamePair(first_name="Thomas", last_name="Muller")]
    matches = match_names([result.name for result in located], queries, settings.fuzzy_threshold)
    exact = [
        match for match in matches
        if match.extracted_name == "Thomas Muller"
        and match.matched_name == "Thomas Muller"
        and match.score == 1.0
    ]
    check(len(exact) == 1, "There is one unique fuzzy pair for Thomas Muller with score 1.0")
    accents = match_names(
        ["María González"], [NamePair(first_name="Maria", last_name="Gonzalez")],
        settings.fuzzy_threshold,
    )
    check(len(accents) == 1 and accents[0].score == 1.0, "Matching ignores accents and case")
    partial = match_names(["John"], [NamePair(first_name="John", last_name="Smith")], 0.90)
    check(not partial, "A substring does not match as a full name at threshold 0.90")

    print(f"\nSUMMARY: {len(located)} located occurrences; {omitted} spans omitted for safety.")
    print("RESULT: real components verified; no HTTP or mocks.")
    print("LIMITATION: does not test general accuracy or replace human review.")


if __name__ == "__main__":
    main()
