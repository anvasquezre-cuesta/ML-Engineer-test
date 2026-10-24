# Document Intelligence Service — Design

Extract person names from scanned PDFs with page-accurate bounding boxes,
fuzzy-match against a vetted list, and answer grounded questions via RAG.

## Component Architecture

Layered with ports/adapters at the tech boundary. External dependencies
(OCR, NER, embeddings, vector store, LLM) are Protocols declared in the
consuming service layer, injected via FastAPI `Depends` from one composition
root (`app/dependencies.py`). No service constructs its own clients.

```
Request → Routers (app/api/) → Services (app/services/) → Protocols
                                                    ↑
                                           Adapters (app/adapters/)
```

- **Routers** (`extract.py`, `rag.py`): thin HTTP handlers, delegate to services
- **Services**: pipeline orchestration; declare Protocol dependencies
- **Adapters**: concrete implementations (tesseract, spaCy, chroma, langchain)
- **Core** (`app/core/`): `config.py` (Settings), `errors.py` (domain→HTTP map),
  `http.py` (`with_retries`)

## Pipeline Sequences

### Extract (`POST /api/extract`)

```
Upload PDF + names[]
→ validate_and_read() (magic bytes, size cap)
→ OCR every page (Tesseract)
→ NER on full text (spaCy en_core_web_sm)
→ deduplicate, merge with caller names
→ fuzzy_match_names() (Levenshtein)
→ pixels_to_points()  ← single conversion site
→ per-name per-page bbox matching
→ ExtractedName[] with BoundingBox[] + FuzzyMatch[]
```

All endpoints are sync `def`; FastAPI runs them on the threadpool.

### RAG (`POST /api/ingest` → `POST /api/ask`)

```
Ingest:
  Upload PDF → validate_and_read()
  → OCR every page
  → chunk_text() (no mid-word cuts)
  → chunk ID = {sha256(doc)}:{page}:{index}  (content-derived)
  → embed each chunk (sentence-transformers)
  → upsert into Chroma vector store
  → IngestResponse(chunks_stored=N)

Ask:
  {"question": "..."}
  → embed question
  → retrieve top-k chunks
  → grounded prompt: chunks verbatim + abstain instruction
  → LLM via LangChainLlm adapter
  → sources = [{doc_id, chunk_text}] from retrieved metadata,
    never parsed from the LLM answer
```

## Technology Choices and Trade-offs

| Component | Choice | Trade-off |
|---|---|---|
| Framework | FastAPI + Pydantic | Standard, typed, fast |
| PDF | PyMuPDF | Reliable, good bbox support |
| OCR | Tesseract | Best OSS OCR; requires binary |
| NER | spaCy en_core_web_sm | Fast, small; not SOTA |
| Fuzzy | thefuzz + python-Levenshtein | Battle-tested, fast |
| Embeddings | sentence-transformers | Local, no API key |
| Vector store | Chroma (embedded) | Zero infra; idempotent via content-derived IDs |
| LLM | ChatOpenAI (langchain-openai) | OpenAI integration; timeout/retry built-in |

**Stack deviations:**
- **LangChain:** Use `langchain-openai`'s `ChatOpenAI` directly rather than a
  wrapper. ChatOpenAI *is* the canonical LangChain OpenAI integration with
  built-in timeout/retry; a wrapper adds abstraction without benefit. Still
  behind our `LLMClient` Protocol for testability.
- **thefuzz:** As suggested — best open-source fuzzy matching library.
- **Chroma embedded:** As suggested — zero-infra, disk-persisted. Content-derived
  IDs make re-ingest idempotent.

## Scaling to 1000+ PDFs/Hour

Current design processes one document at a time. To scale:

- **Concurrency:** Run OCR on all pages in parallel; process documents in
  parallel with bounded concurrency.
- **Vector store:** Switch from embedded Chroma to managed vector DB
  (Qdrant, pgvector) with connection pooling.
- **Batch embedding:** Use `encode()` batches for 10-20x speedup.
- **Async processing:** Use background tasks/Celery for long OCR/ingestion;
  return task ID immediately, poll for completion.
- **Horizontal scaling:** Stateless API workers behind a load balancer;
  persistent shared vector store.

## Failure Modes and Mitigations

| Failure mode | Mitigation |
|---|---|
| Bad PDF (wrong magic, empty, oversized) | `validate_and_read()` → HTTP 422/413 |
| OCR failure | `external_guard()` → `ExternalServiceError` → 502 |
| NER/embedding model missing | Fail fast at startup (lifespan) |
| Chroma unavailable/corrupt | `external_guard()` → 502 |
| LLM call fails/times out | `with_retries()` with backoff → 502 |
| LLM hallucination | Abstain instruction; sources from metadata, not LLM output |
| File handle leaks | `tempfile.mkstemp()` + `os.unlink()` in `finally` |

All external calls wrapped with `with_retries()` (timeout + fixed backoff).
No `except: pass` blocks anywhere in the pipeline.

## Model Routing by Query Complexity

Current design uses one model for all queries. To support routing:

- Inspect question length and structure in `rag_service.generate_answer()`
- Short, factual questions → smaller, faster model
- Complex synthesis → larger model
- Route based on heuristics: length, entity count, keywords
  ("compare", "analyze", "contrast", "evaluate")
- Implement behind the `LLMClient` Protocol for swapability
- Log routing decisions for analysis

## Audit Viewer

`static/index.html` overlays API-returned bounding boxes onto rendered PDF
pages using the same coordinate space (PDF points, 72/inch), confirming name
locations visually.