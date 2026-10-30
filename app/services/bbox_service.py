"""Map person names to their bounding boxes in PDF points.

A name's box is the union of the OCR words its span touches, found by text
offsets (not by string search). Edge punctuation ("Thompson,") stays in the box.
"""

from pathlib import Path

from app.services.ner_service import NameRecognizer, Span, find_person_spans
from app.services.ocr_service import Word, ocr_pages, page_text


def boxes_for_spans(words: list[Word], spans: list[Span]) -> list[dict]:
    """One enclosing box per span, from the words (with start/end) it touches."""
    boxes = []
    for name, start, end in spans:
        hit = [w for w in words if w["start"] < end and w["end"] > start]
        x0, y0 = min(w["x"] for w in hit), min(w["y"] for w in hit)
        x1 = max(w["x"] + w["width"] for w in hit)
        y1 = max(w["y"] + w["height"] for w in hit)
        box = {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}
        boxes.append({"name": name, "page": hit[0]["page"], **box})
    return boxes


def locate_names(
    pages: list[list[Word]], recognizer: NameRecognizer | None = None
) -> list[dict]:
    """Boxes of every person on every page; NER runs once so names propagate."""
    placed = [page_text(words) for words in pages]
    spans = find_person_spans([text for text, _ in placed], recognizer)
    return [
        box
        for (_, words), page_spans in zip(placed, spans, strict=True)
        for box in boxes_for_spans(words, page_spans)
    ]


def find_name_bounding_boxes(pdf_path: str, text: str) -> list[dict]:
    """Return one merged box per person in the PDF; ``text`` is ignored.

    Offsets must come from the OCR of this same PDF, so the text is rebuilt here.
    """
    return locate_names(ocr_pages(Path(pdf_path).read_bytes()))
