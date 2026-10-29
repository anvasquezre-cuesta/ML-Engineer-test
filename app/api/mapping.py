"""Translation between the fixed HTTP contract and domain types (ADR-012)."""

import json

from pydantic import TypeAdapter, ValidationError

from app.application.answer_question import Answer
from app.application.extract_names import ExtractionResult
from app.application.ingest_document import IngestResult
from app.domain.errors import NamesInvalid
from app.domain.name_matching import RequestedName
from app.models import schemas

_NAME_PAIRS = TypeAdapter(list[schemas.NamePair])
# Hundredths of a point (~0.004 mm): far below OCR box precision, hides float noise.
COORDINATE_DECIMALS = 2


def to_requested_names(raw: str) -> list[RequestedName]:
    """Parse the ``names`` form field (JSON list of first/last pairs); ``NamesInvalid`` if not."""
    try:
        pairs = _NAME_PAIRS.validate_python(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise NamesInvalid("names must be a JSON list of {first_name, last_name}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"names{''.join(f'[{p}]' if isinstance(p, int) else f'.{p}' for p in e['loc'])}: "
            f"{e['msg']}"
            for e in exc.errors()
        )
        raise NamesInvalid(problems) from exc
    try:
        return [RequestedName(pair.first_name, pair.last_name) for pair in pairs]
    except ValueError as exc:  # blank after trimming whitespace
        raise NamesInvalid(f"names: {exc}") from exc


def to_extraction_response(result: ExtractionResult) -> schemas.ExtractionResponse:
    """Map the domain result to ``ExtractionResponse`` (boxes in PDF points, top-left)."""
    return schemas.ExtractionResponse(
        extracted_names=[
            schemas.ExtractedName(
                name=occurrence.name,
                bounding_box=schemas.BoundingBox(
                    page_number=occurrence.page_index,
                    x=round(occurrence.box.x, COORDINATE_DECIMALS),
                    y=round(occurrence.box.y, COORDINATE_DECIMALS),
                    width=round(occurrence.box.width, COORDINATE_DECIMALS),
                    height=round(occurrence.box.height, COORDINATE_DECIMALS),
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


def to_ingest_response(result: IngestResult) -> schemas.IngestResponse:
    """Map an ingestion to ``IngestResponse``; re-ingesting the same PDF reports the same count."""
    return schemas.IngestResponse(status="ingested", chunks_stored=result.chunk_count)


def to_rag_response(answer: Answer) -> schemas.RAGResponse:
    """Map an answer to ``RAGResponse``; ``sources`` are always built by code (ADR-006)."""
    return schemas.RAGResponse(answer=answer.text, sources=list(answer.sources))
