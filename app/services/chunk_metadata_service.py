"""Deterministic metadata enrichment for document chunks."""

import re
from pathlib import Path

from app.models.ingestion import (
    ChunkMetadata,
    ChunkedIngestionResult,
    DocumentType,
    MetadataChunk,
)

DOCUMENT_INFORMATION_SECTION = "Document information"
NON_ALPHANUMERIC_PATTERN = re.compile(r"[^a-z0-9]+")


class DeterministicChunkMetadataService:
    """Attach source metadata without an LLM or external dependency."""

    def attach(self, result: ChunkedIngestionResult) -> tuple[MetadataChunk, ...]:
        """Enrich every chunk with stable document and position metadata."""

        job = result.structured.ocr.job
        title = result.structured.document.title
        document_type = self._document_type(title, job.pdf.filename)

        return tuple(
            MetadataChunk(
                text=chunk.text,
                metadata=ChunkMetadata(
                    chunk_id=f"{job.ingestion_id}:{chunk_index:06d}",
                    document_id=job.ingestion_id,
                    filename=job.pdf.filename,
                    document_type=document_type,
                    document_title=title,
                    section=chunk.section_heading or DOCUMENT_INFORMATION_SECTION,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_index=chunk_index,
                    word_count=chunk.word_count,
                ),
            )
            for chunk_index, chunk in enumerate(result.chunks)
        )

    @staticmethod
    def _document_type(title: str, filename: str) -> DocumentType:
        normalized_title = NON_ALPHANUMERIC_PATTERN.sub(" ", title.casefold())
        normalized_filename = NON_ALPHANUMERIC_PATTERN.sub(
            " ",
            Path(filename).stem.casefold(),
        )
        combined = f"{normalized_title} {normalized_filename}"

        if "meeting minutes" in combined:
            return DocumentType.MEETING_MINUTES
        if "memorandum" in combined or "company memo" in combined:
            return DocumentType.MEMO
        if "research" in combined and "report" in combined:
            return DocumentType.RESEARCH_REPORT
        return DocumentType.UNKNOWN
