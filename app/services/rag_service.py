"""RAG service: chunk text and generate answers from retrieved context."""

import hashlib
import logging
from typing import Protocol

from app.core.errors import ExternalServiceError
from app.core.http import with_retries
from app.core.config import get_settings

logger = logging.getLogger("app.services.rag_service")


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


def compute_doc_id(raw: bytes) -> str:
    """Compute content-derived document ID (SHA-256 truncated)."""
    return hashlib.sha256(raw).hexdigest()[:12]


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into word-boundary chunks. Never cuts words in half."""
    words = text.split(" ")
    chunks = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > chunk_size and current:
            chunks.append(current)
            current = word
        else:
            current = current + " " + word if current else word
    if current:
        chunks.append(current)
    return chunks


def ingest_document(raw: bytes, ocr, settings, embedder, store) -> int:
    """OCR all pages, chunk, embed, and store into the vector store.
    Returns the number of chunks stored."""
    doc_id = compute_doc_id(raw)
    npages = ocr.page_count(raw)
    all_chunks = []
    all_metadatas = []

    for page_index in range(npages):
        text, _ = ocr.ocr_page(raw, page_index, settings.ocr_dpi)
        page_chunks = chunk_text(text, settings.chunk_size)
        for idx, chunk in enumerate(page_chunks):
            if chunk.strip():
                all_chunks.append(chunk)
                all_metadatas.append({"doc_id": doc_id, "page": page_index, "chunk_index": idx})

    # Embed and store
    if not all_chunks:
        return 0

    # Wrap embed call in retry
    def _embed_chunks():
        return embedder.embed_documents(all_chunks)

    embeddings = with_retries(
        _embed_chunks,
        retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_backoff_seconds,
        operation=f"embedding doc_id={doc_id}",
    )

    ids = []
    for i, meta in enumerate(all_metadatas):
        ids.append(f"{meta['doc_id']}:{meta['page']}:{meta['chunk_index']}")

    # Wrap store call in retry
    def _store_chunks():
        store.add_chunks(ids, embeddings, all_chunks, all_metadatas)

    with_retries(
        _store_chunks,
        retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_backoff_seconds,
        operation=f"storing chunks doc_id={doc_id}",
    )

    logger.info(
        "ingest_document: doc_id=%s chunks_stored=%d",
        doc_id,
        len(all_chunks),
    )
    return len(all_chunks)


def generate_answer(question: str, embedder, store, llm, top_k) -> dict:
    """Retrieve relevant chunks and generate a grounded answer."""
    settings = get_settings()

    # Wrap embed call in retry
    def _embed_query():
        return embedder.embed_query(question)

    query_embedding = with_retries(
        _embed_query,
        retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_backoff_seconds,
        operation=f"embedding query for '{question}'",
    )

    # Wrap store query in retry
    def _query_store():
        return store.query(query_embedding, top_k)

    results = with_retries(
        _query_store,
        retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_backoff_seconds,
        operation=f"querying store for '{question}'",
    )

    # Build context from retrieved chunks
    context_parts = []
    sources = []
    chunk_ids = []
    for r in results:
        text = r.get("text", "")
        sources.append(text)
        chunk_ids.append(r.get("id", ""))
        context_parts.append(f"[{r.get('id', '')}] {text}")

    if not context_parts:
        # No relevant content found — abstain
        return {"answer": "No relevant content was found in the ingested documents to answer this question.",
                "sources": []}

    context = "\n".join(context_parts)
    prompt = (f"You are a document Q&A assistant. Answer the question using ONLY the "
             f"retrieved context below. If the context does not contain the answer, "
             f"state that it does not instead of inventing one. List the sources you used.\n\n"
             f"Context:\n{context}\n\n"
             f"Question: {question}\n\n"
             f"Answer:")

    try:
        answer = llm.complete(prompt)
    except Exception as e:
        raise ExternalServiceError(f"LLM call failed: {e}") from e

    logger.info(
        "generate_answer: question=%r retrieved_chunk_ids=%s",
        question,
        chunk_ids,
    )
    return {"answer": answer, "sources": sources}
