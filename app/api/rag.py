"""Router for ``POST /api/ingest`` and ``POST /api/ask``."""

from typing import Annotated
from typing import cast

import fastapi

from app import config
from app.models import schemas
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


def upload_settings(request: fastapi.Request) -> config.UploadSettings:
    """Returns the upload limits.

    Args:
        request: The current request.

    Returns:
        The upload settings.
    """
    return cast(config.UploadSettings, request.app.state.settings.upload)


@router.post("/ingest")
async def ingest(  # noqa: DOC501, DOC503
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
    raise NotImplementedError
