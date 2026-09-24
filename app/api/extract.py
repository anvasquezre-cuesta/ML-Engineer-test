"""Router for ``POST /api/extract``."""

from typing import Annotated
from typing import cast

import fastapi
import pydantic
import structlog

from app import config
from app.domain import errors
from app.domain import extraction
from app.domain import pdf_validation
from app.models import schemas
from app.service_layer import extract as extract_service

router = fastapi.APIRouter()
log = structlog.stdlib.get_logger(__name__)

_NAME_PAIRS = pydantic.TypeAdapter(list[schemas.NamePair])


def use_case(request: fastapi.Request) -> extract_service.ExtractNames:
    """Returns the use case built at startup.

    Args:
        request: The current request.

    Returns:
        The extraction use case.
    """
    return cast(extract_service.ExtractNames, request.app.state.extract_names)


def upload_settings(request: fastapi.Request) -> config.UploadSettings:
    """Returns the upload limits.

    Args:
        request: The current request.

    Returns:
        The upload settings.
    """
    return cast(config.UploadSettings, request.app.state.settings.upload)


def parse_names(names: str) -> list[extraction.QueryName]:
    """Parses the ``names`` form field.

    Args:
        names: A JSON list of ``{"first_name", "last_name"}`` objects.

    Returns:
        The queried names.

    Raises:
        errors.InvalidNamesJsonError: If the field is not such a list.
    """
    try:
        pairs = _NAME_PAIRS.validate_json(names)
    except pydantic.ValidationError as exc:
        raise errors.InvalidNamesJsonError() from exc
    return [extraction.QueryName(p.first_name, p.last_name) for p in pairs]


@router.post("/extract")
async def extract(
    pdf_file: fastapi.UploadFile,
    names: Annotated[str, fastapi.Form()],
    extract_names: Annotated[
        extract_service.ExtractNames, fastapi.Depends(use_case)
    ],
    limits: Annotated[config.UploadSettings, fastapi.Depends(upload_settings)],
) -> schemas.ExtractionResponse:
    """Finds every person name in a scanned PDF and fuzzy-matches it.

    Args:
        pdf_file: The uploaded PDF.
        names: JSON list of the names to match against.
        extract_names: The extraction use case.
        limits: Upload limits.

    Returns:
        Every name occurrence with its box in PDF points, and the matches.
    """
    try:
        queries = parse_names(names)
        # One byte past the limit is enough to know the upload is too large.
        content = await pdf_file.read(limits.max_bytes + 1)
    finally:
        await pdf_file.close()
    pdf_validation.validate_pdf(content, limits.max_bytes)
    result = await extract_names(content, queries)
    log.info(
        "extract.completed",
        names_found=len(result.occurrences),
        matches=len(result.matches),
    )
    return schemas.ExtractionResponse(
        extracted_names=[
            schemas.ExtractedName(
                name=occurrence.name,
                bounding_box=schemas.BoundingBox(
                    page_number=occurrence.page_number,
                    x=occurrence.box.x,
                    y=occurrence.box.y,
                    width=occurrence.box.width,
                    height=occurrence.box.height,
                ),
            )
            for occurrence in result.occurrences
        ],
        fuzzy_matches=[
            schemas.FuzzyMatch(
                extracted_name=match.extracted_name,
                matched_name=match.matched_name,
                score=match.score,
            )
            for match in result.matches
        ],
    )
