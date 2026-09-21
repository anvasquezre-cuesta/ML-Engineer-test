"""
Module: app.services.text_chunker
Path: app/services/text_chunker.py
Description: Word-safe text chunking service for RAG documents.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings


class TextChunker:
    """Split document text into overlapping chunks without cutting words."""

    def __init__(self, settings: Settings) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            separators=["\n\n", "\n", " "],
        )

    def split_text(self, text: str) -> list[str]:
        """Split document text while preserving complete words."""

        return self._splitter.split_text(text)
