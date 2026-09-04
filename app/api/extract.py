from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import TypeAdapter, ValidationError

from app.api import deps
from app.api.uploads import read_pdf
from app.core.config import Settings
from app.core.errors import InvalidUpload
from app.models.schemas import ExtractionResponse, NamePair
from app.services.extraction_service import ExtractionPipeline

router = APIRouter()

_name_list = TypeAdapter(list[NamePair])


@router.post("/extract", response_model=ExtractionResponse)
async def extract(
    pdf_file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(deps.settings)],
    pipeline: Annotated[ExtractionPipeline, Depends(deps.extraction)],
    names: Annotated[str, Form()] = "[]",
) -> ExtractionResponse:
    pdf = await read_pdf(pdf_file, settings.max_upload_mb)
    try:
        requested = _name_list.validate_json(names)
    except ValidationError as exc:
        raise InvalidUpload(
            f"names must be a JSON list of first/last name pairs: {exc}", 422
        ) from exc
    # OCR and NER are CPU bound; keep them off the event loop
    return await run_in_threadpool(pipeline.run, pdf, requested)
