"""Build contextual text for chunk embeddings."""

from app.models.ingestion import (
    ContextualizedChunk,
    MetadataIngestionResult,
)


class TitleSectionEmbeddingContextService:
    """Prefix raw chunks with their document title and section."""

    def contextualize(
        self,
        result: MetadataIngestionResult,
    ) -> tuple[ContextualizedChunk, ...]:
        """Create embedding text while preserving clean source text."""

        return tuple(
            ContextualizedChunk(
                text=chunk.text,
                embedding_text=(
                    f"Document: {chunk.metadata.document_title}\n"
                    f"Section: {chunk.metadata.section}\n\n"
                    f"{chunk.text}"
                ),
                metadata=chunk.metadata,
            )
            for chunk in result.chunks
        )
