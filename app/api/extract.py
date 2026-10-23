"""``POST /api/extract``: names + bounding boxes + fuzzy matches.

Thin by design: parse the form, call one service method, map the result to the
response schema. A ``def`` (not ``async def``) endpoint, so FastAPI runs the
CPU-bound OCR and NER in its thread pool and the event loop stays free.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.dependencies import get_app_settings, get_extraction_service
from app.api.uploads import parse_names, read_upload
from app.core.config import Settings
from app.models.schemas import BoundingBox, ExtractedName, ExtractionResponse, FuzzyMatch
from app.services.extraction import ExtractionResult, ExtractionService

router = APIRouter()

# Coordinates are rounded to 0.01 pt: one pixel at 300 DPI is 0.24 pt.
_DECIMALS = 2


@router.post("/extract", response_model=ExtractionResponse)
def extract(
    pdf_file: Annotated[UploadFile, File(description="A scanned PDF")],
    names: Annotated[
        str, Form(description='JSON list of {"first_name": ..., "last_name": ...} objects')
    ],
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ExtractionResponse:
    candidates = parse_names(names)
    pdf = read_upload(pdf_file.file, settings.limits.max_upload_bytes)
    result = service.extract(pdf, [f"{n.first_name} {n.last_name}" for n in candidates])
    return to_response(result)


def to_response(result: ExtractionResult) -> ExtractionResponse:
    return ExtractionResponse(
        extracted_names=[
            ExtractedName(
                name=m.name,
                bounding_box=BoundingBox(
                    page_number=m.page,
                    x=round(m.box.x0, _DECIMALS),
                    y=round(m.box.y0, _DECIMALS),
                    width=round(m.box.width, _DECIMALS),
                    height=round(m.box.height, _DECIMALS),
                ),
            )
            for m in result.mentions
        ],
        fuzzy_matches=[
            FuzzyMatch(extracted_name=m.extracted, matched_name=m.candidate, score=m.score)
            for m in result.matches
        ],
    )
