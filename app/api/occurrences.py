"""Router listing and exporting every stored name occurrence."""

import csv
import io
from typing import Annotated
from typing import Literal
from typing import cast

import fastapi

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


def export_use_case(
    request: fastapi.Request,
) -> occurrence_service.ExportOccurrences:
    """Returns the export use case built at startup.

    Args:
        request: The current request.

    Returns:
        The export use case.
    """
    return cast(
        occurrence_service.ExportOccurrences,
        request.app.state.export_occurrences,
    )


ExportUseCase = Annotated[
    occurrence_service.ExportOccurrences, fastapi.Depends(export_use_case)
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
    export: ExportUseCase,
    export_format: Annotated[
        Literal["json", "csv"], fastapi.Query(alias="format")
    ] = "json",
    document_key: str | None = None,
    name: str | None = None,
) -> fastapi.Response:
    """Returns the current occurrences as a JSON or CSV download.

    The export is read whole before the response starts, so a failure is an
    error response and never a download that looks complete.

    Args:
        export: The export use case.
        export_format: ``json`` or ``csv``.
        document_key: Only this document, if given.
        name: Only names containing it, ignoring case and accents.

    Returns:
        The download, with its row count in ``X-Row-Count``.
    """
    rows = await export(document_key=document_key, name=name)
    if export_format == "csv":
        body, media_type = _csv(rows), "text/csv"
    else:
        body, media_type = _json(rows), "application/json"
    return fastapi.Response(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="occurrences.{export_format}"'
            ),
            "X-Row-Count": str(len(rows)),
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


def _json(rows: list[occurrences.StoredOccurrence]) -> str:
    """Writes the occurrences as one JSON array.

    Args:
        rows: The occurrences.

    Returns:
        The array.
    """
    return "[" + ",".join(_record(r).model_dump_json() for r in rows) + "]"


def _csv(rows: list[occurrences.StoredOccurrence]) -> str:
    """Writes the occurrences as CSV with a header row.

    Args:
        rows: The occurrences.

    Returns:
        The CSV text.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        box = row.box
        writer.writerow(
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
    return buffer.getvalue()
