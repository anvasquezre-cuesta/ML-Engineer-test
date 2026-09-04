import hashlib
import logging
import uuid

from app.models.schemas import RAGResponse
from app.services.interfaces import Embedder, LLMClient, OcrEngine, VectorStore

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Answer the question using only the context below. "
    "If the context does not contain the answer, say you don't know. "
    "Do not invent facts or sources."
)

NO_DOCUMENTS_ANSWER = "No documents have been ingested yet, so I can't answer that."


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Greedy word-packing into chunks of at most `size` characters.

    Words are never split. The last few words of a chunk (up to `overlap`
    characters) are repeated at the start of the next so a sentence cut at a
    boundary is still retrievable.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")
    overlap = min(overlap, size // 2)

    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in text.split():
        if current and length + 1 + len(word) > size:
            chunks.append(" ".join(current))
            kept: list[str] = []
            kept_len = 0
            for prev in reversed(current):
                if kept_len + len(prev) + 1 > overlap:
                    break
                kept.insert(0, prev)
                kept_len += len(prev) + 1
            current, length = kept, kept_len
        current.append(word)
        length += len(word) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


class RagService:
    def __init__(
        self,
        ocr: OcrEngine,
        embedder: Embedder,
        store: VectorStore,
        llm: LLMClient,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
    ):
        self.ocr = ocr
        self.embedder = embedder
        self.store = store
        self.llm = llm
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

    def ingest(self, pdf: bytes, filename: str) -> int:
        pages = self.ocr.run(pdf)
        text = "\n".join(page.text for page in pages)
        chunks = chunk_text(text, self.chunk_size, self.chunk_overlap)
        if not chunks:
            return 0

        # A fresh id per ingest: uploading the same file twice stores it twice instead
        # of overwriting. The content hash goes into the source so duplicates are visible.
        doc_id = uuid.uuid4().hex[:12]
        digest = hashlib.sha256(pdf).hexdigest()[:8]
        ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
        sources = [f"{filename}#{digest}#chunk{i}" for i in range(len(chunks))]

        self.store.add(ids, chunks, self.embedder.embed(chunks), sources)
        log.info("ingested", extra={"doc_id": doc_id, "file": filename, "chunks": len(chunks)})
        return len(chunks)

    async def ask(self, question: str) -> RAGResponse:
        [query_embedding] = self.embedder.embed([question])
        hits = self.store.query(query_embedding, self.top_k)
        if not hits:
            return RAGResponse(answer=NO_DOCUMENTS_ANSWER, sources=[])

        context = "\n\n".join(f"[{i + 1}] {hit.text}" for i, hit in enumerate(hits))
        answer = await self.llm.complete(
            SYSTEM_PROMPT, f"Context:\n{context}\n\nQuestion: {question}"
        )
        # sources come from what we retrieved, never from the model's output
        sources = list(dict.fromkeys(hit.source for hit in hits))
        log.info("answered", extra={"hits": len(hits), "sources": len(sources)})
        return RAGResponse(answer=answer, sources=sources)
