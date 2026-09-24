"""Use case: OCR a PDF, chunk and embed its pages, store them by document."""

import asyncio
import hashlib

from app.domain import extraction
from app.domain import page_text
from app.domain import rag
from app.ports import cpu_runner
from app.ports import embedding
from app.ports import ocr as ocr_port
from app.ports import page_renderer
from app.ports import text_chunker
from app.ports import vector_store


class IngestDocument:
    """Indexes a document so questions can be answered from it."""

    def __init__(
        self,
        renderer: page_renderer.PageRenderer,
        ocr: ocr_port.Ocr,
        chunker: text_chunker.TextChunker,
        embedder: embedding.Embedding,
        store: vector_store.VectorStore,
        cpu: cpu_runner.CpuRunner,
    ) -> None:
        """Initializes the use case.

        Args:
            renderer: Turns the PDF into page images.
            ocr: Reads the words on each page.
            chunker: Splits page text into chunks.
            embedder: Embeds the chunks.
            store: Stores the chunks by document.
            cpu: Runs the blocking rendering, OCR and embedding calls.
        """
        self._renderer = renderer
        self._ocr = ocr
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._cpu = cpu

    async def __call__(self, pdf: bytes, document_key: str) -> rag.IngestResult:
        """Ingests ``pdf`` under ``document_key``.

        The same key with the same content (SHA-256 of the bytes) is skipped.
        The same key with new content deletes the old chunks before storing
        the new ones. Chunk ids include the key, so documents never
        overwrite each other.

        Args:
            pdf: The validated PDF content.
            document_key: Identity of the document, e.g. its filename.

        Returns:
            What the ingest did and how many chunks are stored.
        """
        content_hash = hashlib.sha256(pdf).hexdigest()
        existing = await self._store.get_document(document_key)
        if existing is not None and existing.content_hash == content_hash:
            return rag.IngestResult(
                document_key, rag.IngestStatus.UNCHANGED, existing.chunk_count
            )
        pages = await self._cpu.run(self._renderer.render, pdf)
        texts = await asyncio.gather(*(self._read(page) for page in pages))
        chunks = [
            chunk
            for page, text in zip(pages, texts, strict=True)
            for chunk in self._chunker.split(
                rag.SourcePage(
                    document_key, content_hash, page.page_number, text
                )
            )
        ]
        vectors = await self._cpu.run(
            self._embedder.embed_documents, [chunk.text for chunk in chunks]
        )
        if existing is not None:
            await self._store.delete_document(document_key)
        await self._store.upsert(
            [
                rag.EmbeddedChunk(chunk, vector)
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        status = (
            rag.IngestStatus.INGESTED
            if existing is None
            else rag.IngestStatus.REPLACED
        )
        return rag.IngestResult(document_key, status, len(chunks))

    async def _read(self, page: extraction.PageImage) -> str:
        """Reads one page's text.

        Args:
            page: The rendered page.

        Returns:
            The page text with its layout breaks.
        """
        words = await self._cpu.run(self._ocr.read, page)
        return page_text.build_page_text(words).text
