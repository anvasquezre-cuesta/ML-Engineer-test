"""OCR -> NER -> boxes -> fuzzy match, as one function without HTTP."""

from app.log import log_event
from app.models.schemas import ExtractionResponse, NamePair
from app.services.bbox_service import locate_names
from app.services.fuzzy_service import fuzzy_match_names
from app.services.ner_service import NameRecognizer
from app.services.ocr_service import OcrEngine, ocr_pages


def extract(
    pdf_bytes: bytes,
    names: list[NamePair],
    engine: OcrEngine,
    recognizer: NameRecognizer,
) -> ExtractionResponse:
    """Find the people in a scanned PDF and fuzzy-match them against ``names``."""
    pages = ocr_pages(pdf_bytes, engine)
    boxes = locate_names(pages, recognizer)
    # Pydantic builds the models and ignores the extra keys ("name", "page").
    extracted = [
        {"name": b["name"], "bounding_box": {"page_number": b["page"], **b}}
        for b in boxes
    ]
    matches = fuzzy_match_names(
        [b["name"] for b in boxes], [n.model_dump() for n in names]
    )
    log_event(
        pages=len(pages),
        names_in=len(names),
        names_found=len(boxes),
        matches=len(matches),
    )
    return ExtractionResponse(extracted_names=extracted, fuzzy_matches=matches)
