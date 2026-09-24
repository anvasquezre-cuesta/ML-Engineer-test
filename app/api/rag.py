"""Router for ``POST /api/ingest`` and ``POST /api/ask``."""

from typing import Annotated
from typing import cast

import fastapi

from app import config
from app.domain import pdf_validation
from app.models import schemas
from app.service_layer import ask as ask_service
from app.service_layer import ingest as ingest_service

router = fastapi.APIRouter()


def ingest_use_case(request: fastapi.Request) -> ingest_service.IngestDocument:
    """Returns the ingest use case built at startup.

    Args:
        request: The current request.

    Returns:
        The ingest use case.
    """
    return cast(
        ingest_service.IngestDocument, request.app.state.ingest_document
    )


def ask_use_case(request: fastapi.Request) -> ask_service.AskQuestion:
    """Returns the ask use case built at startup.

    Args:
        request: The current request.

    Returns:
        The ask use case.
    """
    return cast(ask_service.AskQuestion, request.app.state.ask_question)


def upload_settings(request: fastapi.Request) -> config.UploadSettings:
    """Returns the upload limits.

    Args:
        request: The current request.

    Returns:
        The upload settings.
    """
    return cast(config.UploadSettings, request.app.state.settings.upload)


@router.post("/ingest")
async def ingest(
    pdf_file: fastapi.UploadFile,
    ingest_document: Annotated[
        ingest_service.IngestDocument, fastapi.Depends(ingest_use_case)
    ],
    limits: Annotated[config.UploadSettings, fastapi.Depends(upload_settings)],
) -> schemas.IngestResponse:
    """Indexes a PDF under its filename so questions can be asked about it.

    Args:
        pdf_file: The uploaded PDF.
        ingest_document: The ingest use case.
        limits: Upload limits.

    Returns:
        What the ingest did and how many chunks are stored.
    """
    try:
        content = await pdf_file.read(limits.max_bytes + 1)
    finally:
        await pdf_file.close()
    pdf_validation.validate_pdf(content, limits.max_bytes)
    result = await ingest_document(content, pdf_file.filename or "document.pdf")
    return schemas.IngestResponse(
        status=result.status, chunks_stored=result.chunks_stored
    )


@router.post("/ask")
async def ask(
    request: schemas.RAGRequest,
    ask_question: Annotated[
        ask_service.AskQuestion, fastapi.Depends(ask_use_case)
    ],
) -> schemas.RAGResponse:
    """Answers a question from the ingested documents, citing its sources.

    Args:
        request: The question.
        ask_question: The ask use case.

    Returns:
        The answer and the references of the chunks it rests on.
    """
    answer = await ask_question(request.question)
    return schemas.RAGResponse(answer=answer.text, sources=list(answer.sources))
