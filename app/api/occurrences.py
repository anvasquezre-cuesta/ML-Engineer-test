"""Router listing and exporting every stored name occurrence."""

from collections.abc import AsyncIterator
import csv
import io
from typing import Annotated
from typing import Literal
from typing import cast

import fastapi
from fastapi import responses

from app.domain import occurrences
from app.models import schemas
from app.service_layer import occurrences as occurrence_service

CSV_COLUMNS = (
    "occurrence_id",
    "document_key",
    "content_hash",
    "generation",
    "page_number",
    "x",
    "y",
    "width",
    "height",
    "name",
)

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
    """
    return [
        _record(occurrence)
        async for occurrence in query(document_key=document_key, name=name)
    ]


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
    """
    rows = query(document_key=document_key, name=name)
    if export_format == "csv":
        body, media_type = _csv_lines(rows), "text/csv"
    else:
        body, media_type = _json_array(rows), "application/json"
    return responses.StreamingResponse(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="occurrences.{export_format}"'
            )
        },
    )


def _record(
    occurrence: occurrences.StoredOccurrence,
) -> schemas.NameOccurrenceRecord:
    """Maps a stored occurrence to its API shape.

    Args:
        occurrence: The stored occurrence.

    Returns:
        The record.
    """
    return schemas.NameOccurrenceRecord(
        occurrence_id=occurrence.occurrence_id,
        document_key=occurrence.document_key,
        content_hash=occurrence.content_hash,
        generation=occurrence.generation,
        name=occurrence.name,
        bounding_box=schemas.BoundingBox(
            page_number=occurrence.page_number,
            x=occurrence.box.x,
            y=occurrence.box.y,
            width=occurrence.box.width,
            height=occurrence.box.height,
        ),
    )


async def _json_array(
    rows: AsyncIterator[occurrences.StoredOccurrence],
) -> AsyncIterator[str]:
    """Streams the occurrences as one JSON array.

    Args:
        rows: The occurrences.

    Yields:
        Pieces of the array.
    """
    yield "["
    separator = ""
    async for row in rows:
        yield separator + _record(row).model_dump_json()
        separator = ","
    yield "]"


async def _csv_lines(
    rows: AsyncIterator[occurrences.StoredOccurrence],
) -> AsyncIterator[str]:
    """Streams the occurrences as CSV with a header row.

    Args:
        rows: The occurrences.

    Yields:
        One CSV line at a time.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def line(values: list[object]) -> str:
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(values)
        return buffer.getvalue()

    yield line(list(CSV_COLUMNS))
    async for row in rows:
        box = row.box
        yield line(
            [
                row.occurrence_id,
                row.document_key,
                row.content_hash,
                row.generation,
                row.page_number,
                box.x,
                box.y,
                box.width,
                box.height,
                row.name,
            ]
        )
