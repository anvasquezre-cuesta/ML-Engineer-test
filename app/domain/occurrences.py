"""Stored name occurrences, grouped in immutable extraction generations.

A generation holds every occurrence one extraction run found in one version
of a document. It becomes the document's current view only when it is
sealed and promoted with an order number higher than the current one.
"""

import dataclasses
import enum
from typing import Literal

from app.domain import extraction

Source = Literal["sync", "job"]


@dataclasses.dataclass(frozen=True, slots=True)
class StoredOccurrence:
    """One stored occurrence of a person's name.

    Attributes:
        occurrence_id: Unique across documents and generations.
        document_key: The document it was found in.
        content_hash: SHA-256 of the document content.
        generation: The extraction run that found it.
        ordinal: Position in the run's occurrences, in page order.
        name: The name as it appears.
        normalized_name: The name without case, accents or OCR noise.
        page_number: 0-based page index.
        box: Location in PDF points, origin top-left.
    """

    occurrence_id: str
    document_key: str
    content_hash: str
    generation: str
    ordinal: int
    name: str
    normalized_name: str
    page_number: int
    box: extraction.Box


@dataclasses.dataclass(frozen=True, slots=True)
class GenerationManifest:
    """The seal of one extraction run of one document version.

    Attributes:
        document_key: The document.
        generation: Id of the run.
        order: Acceptance order of the request or job that ran it.
        content_hash: SHA-256 of the document content.
        extractor: Fingerprint of the models and settings that ran it.
        occurrence_count: Occurrences stored under the generation.
        source: ``sync`` for ``/api/extract``, ``job`` for the worker.
        job_id: The job that ran it, if any.
    """

    document_key: str
    generation: str
    order: int
    content_hash: str
    extractor: str
    occurrence_count: int
    source: Source
    job_id: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class DocumentHead:
    """The generation a document currently shows.

    Attributes:
        document_key: The document.
        manifest: Seal of the current generation; ``None`` until one is
            promoted.
    """

    document_key: str
    manifest: GenerationManifest | None


class PromoteOutcome(enum.StrEnum):
    """What promoting a sealed generation did."""

    CURRENT = "current"
    SUPERSEDED = "superseded"


class RecordOutcome(enum.StrEnum):
    """What recording an extraction did."""

    RECORDED = "recorded"
    UNCHANGED = "unchanged"
    SUPERSEDED = "superseded"
