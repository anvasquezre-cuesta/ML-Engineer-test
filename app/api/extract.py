"""`POST /api/extract`: validate the upload, delegate to the extraction service."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form
from pydantic import Json

from app.dependencies import get_ocr_engine, get_recognizer, read_pdf
from app.models.schemas import ExtractionResponse, NamePair
from app.services.extraction_service import extract
from app.services.ner_service import NameRecognizer
from app.services.ocr_service import OcrEngine

router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
def extract_names(
    pdf_bytes: Annotated[bytes, Depends(read_pdf)],
    names: Annotated[Json[list[NamePair]], Form()],
    engine: Annotated[OcrEngine, Depends(get_ocr_engine)],
    recognizer: Annotated[NameRecognizer, Depends(get_recognizer)],
):
    return extract(pdf_bytes, names, engine, recognizer)
