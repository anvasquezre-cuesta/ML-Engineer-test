"""POST /api/extract — thin router delegating to services."""

import json

from fastapi import APIRouter, Depends, UploadFile, Form, File

from app.core.config import Settings, get_settings
from app.core.errors import external_guard
from app.services.ocr_service import validate_and_read
from app.dependencies import OcrProvider, get_ocr, get_ner
from app.models.schemas import ExtractionResponse, ExtractedName, BoundingBox, FuzzyMatch
from app.services.bbox_service import find_name_bounding_boxes, pixels_to_points
from app.services.ner_service import extract_names
from app.services.fuzzy_service import fuzzy_match_names, full_name
from app.services.ner_service import NerProvider

router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
def extract(
    file: UploadFile = File(...),
    names_json: str = Form("[]"),
    settings: Settings = Depends(get_settings),
    ocr: OcrProvider = Depends(get_ocr),
    ner: NerProvider = Depends(get_ner),
):
    try:
        names = json.loads(names_json)
    except (json.JSONDecodeError, TypeError):
        names = []
    if not isinstance(names, list):
        names = []
    # Callers may pass plain strings; full_name expects {first_name, last_name}.
    names = [nm if isinstance(nm, dict) else {"first_name": str(nm)} for nm in names]

    raw = validate_and_read(file, settings.max_upload_bytes)

    # Loop over every page. OCR failure on any page surfaces as 502.
    npages = external_guard(ocr.page_count)(raw)
    all_pixel_words: list[dict] = []
    all_text_parts: list[str] = []
    for page_index in range(npages):
        text, pixel_words = external_guard(ocr.ocr_page)(raw, page_index, settings.ocr_dpi)
        all_text_parts.append(text)
        all_pixel_words.extend(pixel_words)

    # Run NER on the full document text
    full_text = "\n".join(all_text_parts)
    detected = external_guard(extract_names)(full_text, ner)

    # Deduplicate: NER may report the same name multiple times in the text.
    # Preserve order while removing duplicates.
    detected = list(dict.fromkeys(detected))

    # Merge with any caller-provided names
    for nm in names:
        full = full_name(nm)
        if full and full not in detected:
            detected.append(full)

    # Fuzzy match against caller-provided names
    fuzzy_results = fuzzy_match_names(detected, names, settings.fuzzy_match_threshold)
    fuzzy_matches = [
        FuzzyMatch(
            extracted_name=r["extracted_name"],
            matched_name=r["matched_name"],
            score=r["score"],
        )
        for r in fuzzy_results
    ]

    # Pixel→point conversion happens here, exactly once (AD-4)
    words = pixels_to_points(all_pixel_words, settings.ocr_dpi)

    # Group words by page — matching must stay within one page's word list
    page_words: dict[int, list[dict]] = {}
    for w in words:
        page_words.setdefault(w["page"], []).append(w)

    results = []
    for name in detected:
        for page in sorted(page_words.keys()):
            for box in find_name_bounding_boxes(name, page_words[page]):
                results.append(ExtractedName(
                    name=name,
                    bounding_box=BoundingBox(
                        page_number=box["page"],
                        x=box["x"],
                        y=box["y"],
                        width=box["width"],
                        height=box["height"],
                    ),
                ))

    return ExtractionResponse(extracted_names=results, fuzzy_matches=fuzzy_matches)
