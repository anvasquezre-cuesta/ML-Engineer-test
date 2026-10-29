# `POST /api/ingest` end to end

## Metadata
- **ID**: T-003 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O6, O3, O4 · TRD section(s) §2 (Ingest flow), §7, §8, §10, ADR-007, ADR-008, ADR-009, ADR-015; CONSTITUTION §4.5, §8, §9
- **Depends on**: T-001 · **Wave**: 2
- **Files likely touched**: `app/application/ports.py` (`Embedder`, `VectorStore`), `app/application/` (`IngestDocument`), `app/infrastructure/` (sentence-transformers embedder, Chroma store, settings), `app/api/rag.py`, `app/api/dependencies.py`, `app/main.py`, `app/domain/errors.py`, `pyproject.toml`, `uv.lock`, `.env.example`, `tests/fakes/`, `tests/unit/`, `tests/integration/`, `tests/e2e/`
- **Design**: likely-needed (two new ports — `Embedder`, `VectorStore` — whose shape T-005 and T-006 build on)

## Goal
Let a client index a scanned PDF for question answering: the service OCRs every page,
chunks it (T-001), embeds the chunks and stores them in Chroma under IDs that never
collide across documents, so later questions can be answered from it.

## User Story
As a compliance reviewer (or the system that serves them)
I want to upload a scanned PDF once and have its content indexed
So that I can later ask questions about it and get answers that point to its pages

## Functional Description
- Request: `multipart/form-data` with `pdf_file`. Response: `IngestResponse` exactly as in `schemas.py`: `status = "ingested"`, `chunks_stored` = number of chunks stored for this document.
- Upload validation reuses the extraction epic's `read_pdf_upload` unchanged (magic bytes, empty, size, page count, encrypted, unreadable → same 4xx codes as `/api/extract`).
- `IngestDocument` use case (application): OCR every page with the existing `read_pages` → chunk with T-001 (`max_tokens = CHUNK_MAX_TOKENS`, `count_tokens` from the `Embedder`) → embed all chunk texts in one batch → **replace** the document's chunks in the store (delete chunks with this `document_id`, then upsert the new ones) → return the count.
- **IDs (ADR-007):** `document_id` = first 16 hex chars of SHA-256 of the PDF bytes; chunk id = `{document_id}:{chunk_index}`. Ingesting B never touches A's chunks; ingesting A twice leaves exactly one copy of A.
- **Stored per chunk:** id, embedding, text, and metadata `document_id`, `file_name`, `page`, `chunk_index`. `file_name` is the upload's file name, or the `document_id` when the client sent none.
- **`Embedder` port:** embeds passages and questions (the e5 `passage: ` / `query: ` prefixes are applied inside the adapter — the application never sees them) and counts tokens with the model's tokenizer. Adapter: sentence-transformers with `intfloat/multilingual-e5-small` (ADR-009), loaded once at startup, CPU-only torch.
- **`VectorStore` port:** replace a document's chunks, search by embedding (top-n ids + chunk data), and return all stored chunks (needed by T-005's BM25). Adapter: Chroma `PersistentClient` at `VECTOR_STORE_PATH`, collection `VECTOR_STORE_COLLECTION`, cosine space, embeddings always passed explicitly (Chroma's default embedding function never runs) — ADR-008. Client exceptions become `VectorStoreUnavailable` (503).
- A document with no OCR words yields `chunks_stored = 0` and `200` (not an error); its previous chunks, if any, are removed.
- New settings (`DOCINTEL_*`, documented in `.env.example`): `EMBEDDING_MODEL`, `CHUNK_MAX_TOKENS` (default 250, must be < 512 — rejected at startup otherwise), `VECTOR_STORE_PATH`, `VECTOR_STORE_COLLECTION`.
- Route is sync `def` (CPU work in the threadpool) — TRD §8.
- Logging: one `ingest_completed` event with `document_id`, page count, chunk count and per-stage durations (ocr, chunk, embed, store). No text, no names, no file name.

## Main Flow
1. Client posts `meeting_minutes.pdf` to `/api/ingest`.
2. Router validates the upload and calls `IngestDocument`.
3. Use case OCRs both pages, chunks them, embeds the chunks and replaces the document's chunks in Chroma.
4. Router returns `200 {"status": "ingested", "chunks_stored": N}` with N ≥ 2 (one per page at least).

## Alternative Flows
- **Same PDF ingested twice**: Given A already ingested → `200` with the same `chunks_stored`; the store holds exactly that many chunks for A.
- **Invalid upload**: Given a non-PDF, empty, oversized, too-long, encrypted or unreadable file → the same 4xx and error code as `/api/extract`.
- **Document with no text**: Given a PDF whose OCR yields no words → `200` with `chunks_stored: 0`.
- **Vector store failure**: Given the Chroma client raises → `503` with `error.code = "vector_store_unavailable"` and the `request_id`.
- **OCR engine unavailable**: Given Tesseract is missing → `503` with `error.code = "ocr_unavailable"`.

## Acceptance Criteria
1. **Second ingest does not overwrite the first** *(e2e, real Chroma in a temp dir)*
   - Given `company_memo.pdf` then `meeting_minutes.pdf` ingested
   - When all stored chunks are listed
   - Then chunks of both documents are present, their ids share no prefix, and their count equals the sum of both `chunks_stored`
2. **Re-ingest is idempotent**
   - Given `company_memo.pdf` ingested twice
   - When the store is inspected
   - Then it holds exactly `chunks_stored` chunks with that `document_id`, ids `{document_id}:0..n-1`
3. **Every page is indexed** *(e2e)*
   - Given each 2-page sample PDF
   - When it is ingested
   - Then stored chunks carry both `page` 0 and `page` 1, and every chunk's token count (embedder tokenizer) is ≤ `CHUNK_MAX_TOKENS`
4. **Use case testable without HTTP**
   - Given `IngestDocument` built with fake ports (scripted OCR pages, fake embedder, in-memory store) and no FastAPI import in the test
   - When it runs on a 2-page fake document
   - Then the in-memory store receives the expected chunk ids, texts and metadata
5. **Store failure maps to 503**
   - Given a fake `VectorStore` that raises `VectorStoreUnavailable`
   - When `/api/ingest` is called
   - Then the response is `503` with `error.code = "vector_store_unavailable"` and a `request_id`

## Technical Notes *(only if applicable)*
- New dependencies `sentence-transformers`, `torch` (CPU wheel index), `chromadb` are already decided by ADR-008/ADR-009 — pin them; no other library.
- Chroma must not download its default embedding model at any point — ADR-008.
- Temp files, if any, are removed by context managers — PRD §Resource management.

## Agent Validation
Checklist for a reviewer agent to determine the ticket was implemented correctly:

- [ ] Every acceptance criterion passes.
- [ ] No contradictions between expected behavior and the implementation.
- [ ] No open functional decisions remain.
- [ ] Main and alternative flows fully covered.
- [ ] No semantic ambiguity.
- [ ] The functionality is automatically testable.
- [ ] The implementation stays consistent with the other tickets.
- [ ] Documentation remains in sync with implemented behavior.
- [ ] No hidden functional dependencies.
- [ ] Behavior can be validated by another agent without human intervention.
- [ ] No chunk id is built from a counter alone: every id contains the content-hash `document_id`.
- [ ] A captured `ingest_completed` log record contains no chunk text and no file name.
- [ ] `DOCINTEL_CHUNK_MAX_TOKENS=512` makes startup fail with `configuration_invalid` naming the variable.
