"""
Module: app.api.extract
Path: app/api/extract.py
Description: API endpoint for person-name extraction from scanned PDFs.
"""

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.dependencies import get_extraction_service, get_ocr_service
from app.models.schemas import ExtractionResponse, NamePair
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService

router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
async def extract_names(
    pdf_file: UploadFile = File(...),
    names: str = Form(...),
    ocr_service: OCRService = Depends(get_ocr_service),
    extraction_service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionResponse:
    """Extract person names and their PDF-space bounding boxes."""

    if not pdf_file.filename:
        raise HTTPException(
            status_code=400,
            detail="A PDF file is required.",
        )

    try:
        TypeAdapter(list[NamePair]).validate_python(json.loads(names))
    except (json.JSONDecodeError, ValidationError):
        raise HTTPException(
            status_code=400,
            detail="names must be a valid JSON list of name objects.",
        ) from None

    if not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file must be a PDF.",
        )

    with tempfile.NamedTemporaryFile(
        suffix=".pdf",
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)

        while chunk := await pdf_file.read(1024 * 1024):
            temporary_file.write(chunk)

    try:
        document = ocr_service.extract(str(temporary_path))
        results = extraction_service.extract(document)

        return ExtractionResponse(
            extracted_names=[
                {
                    "name": result.name,
                    "bounding_box": {
                        "page_number": result.page_number,
                        "x": result.x,
                        "y": result.y,
                        "width": result.width,
                        "height": result.height,
                    },
                }
                for result in results
            ],
            fuzzy_matches=[],
        )
    finally:
        temporary_path.unlink(missing_ok=True)
