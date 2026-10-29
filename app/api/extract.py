"""`POST /api/extract` — thin driving adapter: parse, call the use case, map (ADR-012).

Sync ``def`` on purpose: OCR and NER are CPU-bound, so FastAPI runs this in its threadpool
instead of blocking the event loop (TRD §8).
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.api.dependencies import ContainerDep
from app.api.mapping import to_extraction_response, to_requested_names
from app.api.upload import read_pdf_upload
from app.models.schemas import ExtractionResponse

router = APIRouter()

DESCRIPTION = """Upload a scanned PDF (`pdf_file`) and, optionally, the people to check
(`names`: JSON list of `{"first_name", "last_name"}`; omitted means `[]`).

The file is validated by content (PDF signature, size, encryption, page count) before
any OCR; each rejection has its own `error.code`.

Returns one `extracted_names` entry per occurrence of a PERSON, ordered by page then
reading order. `page_number` is **0-based**; `x`, `y`, `width`, `height` are in **PDF
points** (1/72 inch) with the origin at the **top-left** of the page and `y` growing
down. `fuzzy_matches` lists each extracted name scoring at or above the configured
threshold (0..1) against a requested name."""


@router.post("/extract", response_model=ExtractionResponse, description=DESCRIPTION)
def extract(
    container: ContainerDep,
    pdf_file: Annotated[UploadFile | None, File()] = None,
    names: Annotated[str, Form()] = "[]",
) -> ExtractionResponse:
    """Extract person names with page and box, and match them to the requested names."""
    pdf = read_pdf_upload(pdf_file, container.upload_limits, container.rasterizer)
    requested = to_requested_names(names)
    return to_extraction_response(container.extract_names.execute(pdf, requested))
