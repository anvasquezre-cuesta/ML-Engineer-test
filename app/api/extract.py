"""
Module: app.api.extract
Path: app/api/extract.py
Description: HTTP endpoint for document name extraction and matching.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.dependencies import (
    get_extraction_service,
    get_ocr_service,
    get_pdf_upload_service,
)
from app.models.schemas import ExtractionResponse, NamePair
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService
from app.services.pdf_upload_service import PDFUploadError, PDFUploadService

router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
async def extract_names(
    pdf_file: UploadFile = File(...),
    names: str = Form(...),
    ocr_service: OCRService = Depends(get_ocr_service),
    extraction_service: ExtractionService = Depends(get_extraction_service),
    pdf_upload_service: PDFUploadService = Depends(get_pdf_upload_service),
) -> ExtractionResponse:
    """Extract person names from a PDF and fuzzy-match them against candidates."""

    if not pdf_file.filename:
        raise HTTPException(status_code=400, detail="A PDF file is required.")

    try:
        name_pairs = TypeAdapter(list[NamePair]).validate_python(json.loads(names))
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

    temporary_path = None

    try:
        try:
            temporary_path = pdf_upload_service.save_validated_pdf(pdf_file.file)
        except PDFUploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        document = ocr_service.extract(str(temporary_path))

        candidate_names = [
            f"{name_pair.first_name} {name_pair.last_name}" for name_pair in name_pairs
        ]

        extraction_result = extraction_service.extract(
            document=document,
            candidate_names=candidate_names,
        )

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
                for result in extraction_result.extracted_names
            ],
            fuzzy_matches=[
                {
                    "extracted_name": match.extracted_name,
                    "matched_name": match.matched_name,
                    "score": match.score,
                }
                for match in extraction_result.fuzzy_matches
            ],
        )
    finally:
        pdf_file.file.close()

        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
