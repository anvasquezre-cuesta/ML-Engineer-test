"""
Module: app.models.ingestion
Path: app/models/ingestion.py
Description: Internal models for document ingestion and chunk traceability.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkMetadata:
    """Represent traceability metadata for an ingested document chunk."""

    document_id: str
    source: str
    page_number: int
    chunk_index: int


@dataclass(frozen=True)
class IngestionResult:
    """Represent the outcome of a document ingestion operation."""

    document_id: str
    chunks_stored: int
