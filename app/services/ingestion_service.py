"""Orchestration helpers for the document-ingestion pipeline."""

from collections.abc import Callable
from uuid import UUID, uuid4

from app.models.ingestion import IngestionJob, ValidatedPDFUpload

IngestionIdFactory = Callable[[], UUID]


def create_ingestion_job(
    pdf: ValidatedPDFUpload,
    *,
    id_factory: IngestionIdFactory = uuid4,
) -> IngestionJob:
    """Create uniquely identified state for one validated ingestion request."""

    return IngestionJob(ingestion_id=id_factory(), pdf=pdf)
