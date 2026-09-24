"""Router listing and exporting every stored name occurrence."""

from typing import Annotated
from typing import Literal
from typing import cast

import fastapi
from fastapi import responses

from app.models import schemas
from app.service_layer import occurrences as occurrence_service

router = fastapi.APIRouter()


def query_use_case(
    request: fastapi.Request,
) -> occurrence_service.QueryOccurrences:
    """Returns the query use case built at startup.

    Args:
        request: The current request.

    Returns:
        The query use case.
    """
    return cast(
        occurrence_service.QueryOccurrences,
        request.app.state.query_occurrences,
    )


QueryUseCase = Annotated[
    occurrence_service.QueryOccurrences, fastapi.Depends(query_use_case)
]


@router.get("/occurrences")
async def list_occurrences(
    query: QueryUseCase,
    document_key: str | None = None,
    name: str | None = None,
) -> list[schemas.NameOccurrenceRecord]:
    """Lists the current occurrences, optionally by document and name.

    Args:
        query: The query use case.
        document_key: Only this document, if given.
        name: Only names containing it, ignoring case and accents.

    Returns:
        The occurrences, document by document.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


@router.get("/occurrences/export")
async def export_occurrences(
    query: QueryUseCase,
    export_format: Annotated[
        Literal["json", "csv"], fastapi.Query(alias="format")
    ] = "json",
    document_key: str | None = None,
    name: str | None = None,
) -> responses.StreamingResponse:
    """Streams the current occurrences as a JSON or CSV download.

    Args:
        query: The query use case.
        export_format: ``json`` or ``csv``.
        document_key: Only this document, if given.
        name: Only names containing it, ignoring case and accents.

    Returns:
        The download.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError
