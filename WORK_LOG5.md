# Block 6 — Final Assignment Review

## Objective

Perform a final engineering review of the implemented Document Intelligence Service against the Cuesta Partners ML Engineer take-home requirements before moving to final documentation.

The review focused on:

* architecture and separation of responsibilities;
* configuration and dependency injection;
* resilience, retries, and timeouts;
* validation and resource management;
* observability and logging;
* OCR, NER, bounding-box, and fuzzy-matching correctness;
* RAG correctness, grounding, retrieval behavior, and safety;
* testing strategy and end-to-end validation.

The goal was to identify genuine gaps without adding unnecessary features or overengineering the solution.

---

## 6.1 — Architecture Review

### Objective

Verify that the implementation follows the requested production-oriented architecture, including separation of concerns, dependency injection, SOLID principles, and testable application services.

### Review

The implementation is organized into clear layers:

* **HTTP/API layer**

  * `app/api/extract.py`
  * `app/api/rag.py`

* **Application/service layer**

  * `ExtractionService`
  * `IngestionService`
  * `RAGService`
  * `OCRService`
  * `FuzzyMatchService`
  * `PDFUploadService`
  * `EmbeddingService`
  * `TextChunker`
  * `VectorStoreService`
  * `OllamaLLMProvider`

* **Internal models**

  * OCR models
  * extraction models
  * fuzzy-match models
  * ingestion models

* **Infrastructure/integration boundaries**

  * PyMuPDF
  * Tesseract/PyTesseract
  * spaCy
  * Hugging Face embeddings
  * ChromaDB
  * Ollama

* **Configuration/composition**

  * `app/config.py`
  * `app/dependencies.py`

A particularly strong abstraction is the `LLMProvider` Protocol. `RAGService` depends on the application-level contract rather than directly depending on Ollama.

Concrete implementations are assembled in `app/dependencies.py`, which acts as the composition root.

The routers remain sufficiently thin. They handle HTTP-specific responsibilities such as multipart input, validation, temporary-file lifecycle, and response mapping, while the main business algorithms remain in services.

The business logic can also be exercised without HTTP. Direct testing of `RAGService` confirmed that the retrieval and generation workflow works independently of FastAPI.

### Decision

No architectural changes were necessary.

Adding additional abstractions, such as a `VectorStore` Protocol, was considered unnecessary for the current scope because `VectorStoreService` already encapsulates ChromaDB and provides a clear application boundary.

### Validation

Architecture review completed successfully.

### Design principles

* Separation of concerns
* Dependency injection
* Single responsibility
* Dependency inversion through `LLMProvider`
* Testability
* Thin API layer
* Explicit composition root

### Status

**6.1 completed — no code changes required.**

---

## 6.2 — Configuration Review

### Objective

Verify that configuration is centralized, environment-overridable, and sufficiently provider-neutral.

### Review

`app/config.py` centralizes configuration for:

* Tesseract path;
* OCR DPI;
* fuzzy-match threshold;
* spaCy model;
* embedding model;
* ChromaDB persistence directory;
* ChromaDB collection;
* RAG chunk size;
* chunk overlap;
* retrieval `top_k`;
* LLM provider;
* LLM model;
* LLM base URL;
* LLM API key;
* LLM temperature;
* LLM timeout;
* LLM retry count;
* upload size limit.

Pydantic Settings is configured with:

* `APP_` environment-variable prefix;
* `.env` support;
* ignored unknown environment variables.

The local default is Ollama/Llama 3, but the provider/model/base URL are configuration values rather than hard-coded values in the RAG service.

The API-key setting is present for future provider configurations, but Ollama does not require it. No unsupported claim of OpenAI implementation was made because only the Ollama provider has actually been implemented.

Potential stronger validation rules were considered, such as validating DPI, thresholds, chunk relationships, `top_k`, timeout, and retry counts. No concrete failure requiring those changes was identified, so additional validation was not added solely for theoretical completeness.

### Validation

Configuration defaults and environment-variable overrides were tested previously, including `APP_LLM_API_KEY`.

### Status

**6.2 completed — no code changes required.**

---

## 6.3 — Resilience Review

### Objective

Review external-service failures, retries, timeouts, and controlled error propagation.

### Review

The LLM provider has:

* configurable timeout;
* configurable retry count;
* multiple generation attempts;
* translation of provider failures into `LLMProviderError`.

The vector-store adapter translates ChromaDB failures into `VectorStoreError`.

The API maps infrastructure failures to controlled responses:

* LLM failure → HTTP 502;
* vector-store failure → HTTP 503.

Other failures are not silently swallowed:

* OCR failures propagate;
* invalid PDF uploads produce HTTP 400;
* malformed requests are rejected by validation;
* unavailable retrieval context produces a safe RAG response.

The vector store does not have artificial network retries because the current ChromaDB deployment is embedded/local rather than a remote network service.

Exponential backoff was considered but not added because the assignment does not require it and the current implementation does not establish a need for additional retry complexity.

### Validation

Unit and integration tests verified:

* LLM failure;
* LLM retry behavior;
* vector-store failure;
* controlled API error responses;
* OCR failure propagation.

### Status

**6.3 completed — no additional production changes required.**

---

## 6.4 — Validation and Resource Management Review

### Objective

Verify input validation, PDF validation, temporary-file lifecycle, and external resource cleanup.

### Review

Uploaded PDFs are validated by inspecting their actual content with PyMuPDF rather than relying only on the filename extension.

The upload service enforces:

* non-empty uploads;
* maximum upload size;
* readable PDF content;
* valid PDF structure.

Request schemas provide validation for:

* name pairs;
* RAG questions;
* bounding-box values;
* fuzzy-match scores.

Temporary upload files are removed after processing, including failure paths.

Uploaded file handles are explicitly closed.

PyMuPDF resources use context managers.

### Issue encountered

During development, invalid-PDF cleanup on Windows initially produced a `PermissionError` because PyMuPDF still held the temporary file open during validation.

### Resolution

PDF validation was changed to operate on bounded bytes:

```text
temporary file
      ↓
read validated-size bytes
      ↓
PyMuPDF opens bytes as PDF
      ↓
validation
      ↓
file cleanup
```

This removed the Windows file-lock problem while preserving PDF-content validation.

### Validation

Unit tests cover:

* empty uploads;
* oversized uploads;
* malformed PDFs;
* temporary-file cleanup;
* successful validation.

Integration tests also exercise real valid PDF uploads.

### Status

**6.4 completed — issue identified and resolved.**

---

## 6.5 — Observability and Logging Review

### Objective

Verify that the application provides useful operational information without unnecessarily logging document content, prompts, answers, or sensitive information.

### Review

Standard Python logging is used with structured event fields through `extra`.

`IngestionService` logs:

* ingestion start;
* document ID;
* pages processed;
* chunks stored;
* duration;
* success/failure status;
* failure type.

`RAGService` logs:

* generation start;
* retrieval configuration;
* provider/model;
* number of retrieved chunks;
* retrieved chunk IDs;
* source count;
* duration;
* success/failure status.

The implementation deliberately avoids logging:

* full document text;
* full retrieved context;
* full prompts;
* user questions;
* generated answers;
* unnecessary PII.

### Changes made during review

The review identified that failure paths in `IngestionService` and `RAGService` needed explicit structured failure logging.

Failure logging was added to both services.

An initially existing `# noqa: BLE001` in `IngestionService` was found to be unnecessary after the change and was removed using Ruff.

The broad exception in `OllamaLLMProvider` remains intentionally scoped to the external-provider boundary because provider libraries can expose different exception types; the exception is translated into the application's domain error.

### Validation

Focused tests and Ruff validation passed after the logging changes.

### Status

**6.5 completed — targeted observability improvements implemented and validated.**

---

## 6.6 — OCR, NER, Bounding-Box, and Fuzzy-Matching Correctness Review

### Objective

Verify the correctness of the document-extraction workflow against the assignment requirements.

### OCR review

The OCR implementation:

* processes every PDF page;
* uses zero-based page numbering;
* renders pages at configurable DPI;
* obtains word-level OCR coordinates;
* converts image coordinates into PDF points using the 72 points/inch conversion.

### NER review

spaCy is used to extract only `PERSON` entities.

### Bounding-box review

OCR word positions are mapped to NER character spans.

The matching words are combined into a bounding box represented in PDF coordinates.

### Fuzzy matching review

Names are normalized by:

* Unicode normalization;
* accent removal;
* case folding;
* punctuation normalization;
* whitespace normalization.

`thefuzz.fuzz.ratio` provides the similarity score.

The threshold is configurable and defaults to `0.90`.

### Real validation

Real sample data confirmed:

* `RICHARD HERNANDEZ` → `Richard Hernandez`, score `1.0`;
* `Thomas Müller` → `Thomas Muller`, score `1.0`;
* `Kevin OBrien` → `Kevin O'Brien`, score `0.96`;
* `Richard X` → no match.

Bounding boxes and page numbers were also verified against the real sample PDF.

### Status

**6.6 completed — no code changes required.**

---

## 6.7 — RAG Correctness, Grounding, and Safety Review

### Objective

Verify that the RAG implementation is correct, explainable, appropriately scoped, and resistant to unsupported answers.

### Retrieval architecture

The implementation uses:

```text
OCR
 ↓
page text
 ↓
word-safe recursive chunking
 ↓
Hugging Face embeddings
 ↓
ChromaDB
 ↓
similarity retrieval
 ↓
grounded LLM prompt
 ↓
answer + application-controlled sources
```

Chunks are configured at approximately:

* 500 characters;
* 50-character overlap.

The splitter uses paragraph, newline, and space separators without a character-level empty-string fallback. This preserves uninterrupted words.

Chunk metadata includes:

* `document_id`;
* `source`;
* `page_number`;
* `chunk_index`.

Vector IDs are generated using UUID4, preventing collisions across ingestion operations.

### Retrieval evaluation

Initial retrieval used `top_k=5`.

During evaluation, the question:

> “How much external funding did the Research Department secure?”

failed because the correct `$1.8M` information was not retrieved within the first five results.

Expanding retrieval to `top_k=12` exposed the correct chunk at rank 11 and allowed the headline answer to be recovered.

This was a genuine evaluation-driven configuration change rather than arbitrary tuning.

### Grounding and safety

The RAG prompt explicitly instructs the LLM to:

* use only retrieved document context;
* avoid outside knowledge;
* state that the answer is unavailable when sufficient context is absent;
* treat document content as data rather than instructions.

Source attribution is generated from retrieved document metadata by the application rather than being generated by the LLM.

When no context is retrieved, the service returns:

> “The answer is not available from the provided documents.”

and does not call the LLM.

### Known limitation identified during evaluation

For the `$1.8M` funding question, increasing `top_k` allowed the correct headline amount to be retrieved, but Llama 3 did not reproduce the complete grant breakdown consistently.

This was recorded as a limitation of the current simple retrieval/generation approach rather than addressed through unnecessary reranking, hybrid retrieval, query rewriting, or other advanced mechanisms.

### Validation

Representative questions were tested:

* Vice President of Engineering → correct answer;
* AWS migration → correct `Q3 2024`;
* Research Department funding → correct `$1.8M` headline after retrieval adjustment;
* unavailable employee turnover information → appropriate refusal/unavailable response.

Real Llama 3 integration was also validated.

### Status

**6.7 completed — no additional retrieval architecture added.**

---

# 6.8 — Testing Strategy and Automated E2E Review

## Objective

Complete the testing-strategy review and add one genuine automated end-to-end test covering the principal document-ingestion-to-RAG workflow.

### Testing structure reviewed

The repository separates tests into:

```text
tests/
├── unit/
├── integration/
└── e2e/
```

Unit tests cover individual services and failure behavior.

Integration tests cover the FastAPI API layer and service boundaries.

Manual E2E validation had already been performed during Block 5 using:

* real FastAPI;
* real sample PDFs;
* real OCR;
* real embeddings;
* real ChromaDB;
* real Ollama/Llama 3.

The remaining gap was that `tests/e2e/` did not yet contain an automated E2E test.

### E2E test design

A single focused E2E test was added:

`tests/e2e/test_document_intelligence_e2e.py`

The test exercises the real workflow:

```text
meeting_minutes.pdf
        ↓
POST /api/ingest
        ↓
PDF validation
        ↓
OCR
        ↓
chunking
        ↓
embeddings
        ↓
ChromaDB
        ↓
POST /api/ask
        ↓
retrieval
        ↓
Llama 3
        ↓
answer + source
```

The assertions verify:

* ingestion returns HTTP 200;
* ingestion stores at least one chunk;
* question answering returns HTTP 200;
* the answer contains `Q3 2024`;
* `meeting_minutes.pdf` appears in the returned sources.

### E2E test isolation

The E2E test is marked:

```text
@pytest.mark.e2e
```

Pytest configuration separates it from the normal regression suite:

```text
uv run pytest -q
```

runs the normal unit/integration suite, while:

```text
uv run pytest -q -m e2e
```

explicitly runs the environment-dependent E2E tests.

This prevents the normal regression suite from depending on a locally running Ollama instance.

### Initial validation

After adding the marker configuration:

```text
uv run pytest -q
```

produced:

**44 passed in 18.93s**

Running:

```text
uv run pytest -q -m e2e
```

before the E2E test existed produced:

**44 deselected**

This confirmed that the marker configuration was functioning as intended.

The new E2E module was then formatted and checked with Ruff:

```text
1 file reformatted
All checks passed!
```

### Initial E2E execution

The first real E2E execution ran for approximately 3 minutes 32 seconds and failed during `/api/ask`:

```text
1 failed, 44 deselected in 211.96s
```

The ingestion portion succeeded.

Evidence from the run included:

* Page 0 OCR: 198 OCR entries / 149 OCR words;
* Page 1 OCR: 178 OCR entries / 134 OCR words;
* embedding model initialized;
* `/api/ingest` returned success;
* failure occurred during RAG generation;
* `/api/ask` returned HTTP 502;
* `RAGService` emitted `rag_generation_failed`.

### Diagnostic investigation

The failure was not immediately attributed to a code defect.

The following checks were subsequently performed.

#### Direct Ollama/Llama 3 test

Llama 3 responded successfully:

```text
E2E Llama 3 is working.
```

#### Direct application LLM-provider test

`OllamaLLMProvider` successfully generated:

```text
Application Llama 3 is working.
```

#### Direct RAG-service test

`RAGService.generate_answer(...)` successfully returned:

```text
According to document 4, TECHNOLOGY UPDATE, the full migration to AWS is expected to be completed by Q3 2024.
```

with the expected source list.

#### FastAPI TestClient test

A direct `TestClient` request to `/api/ask` subsequently returned:

```text
Status: 200
```

with:

```text
{
    "answer": "... full migration to AWS ... Q3 2024.",
    "sources": [
        "meeting_minutes.pdf",
        "company_memo.pdf",
        "research_report.pdf"
    ]
}
```

### Current interpretation

The evidence indicates that the first E2E failure was a transient local LLM/runtime failure rather than an identified defect in:

* OCR;
* ingestion;
* embeddings;
* ChromaDB;
* RAG retrieval;
* prompt construction;
* `OllamaLLMProvider`;
* FastAPI `/api/ask`.

The existing application behavior correctly translated the exhausted provider failure into HTTP 502.

### Important testing decision

The E2E test was **not weakened by adding its own retry loop**.

Adding test-level retries merely to turn an intermittent infrastructure failure into a green test would conceal genuine failures and reduce the value of the E2E test.

The production LLM provider already has retry behavior. The E2E test should continue to exercise the real application behavior and fail when the application cannot complete the workflow.

### Current status

**6.8 is in progress.**

The E2E test implementation and diagnostics are complete, but the final marked E2E test should be rerun after the transient failure to establish the final automated E2E result.

---

# Block 6 Overall Status

### Completed reviews

* **6.1 Architecture** — passed; no changes required.
* **6.2 Configuration** — passed; no changes required.
* **6.3 Resilience** — passed; no changes required.
* **6.4 Validation/resource management** — passed; Windows cleanup issue resolved.
* **6.5 Observability/logging** — passed; targeted failure logging added.
* **6.6 OCR/fuzzy correctness** — passed; real sample validation completed.
* **6.7 RAG correctness/grounding** — passed; retrieval configuration adjusted based on evaluation.
* **6.8 Testing/E2E** — implementation complete; final automated E2E confirmation pending.

### Engineering principles reinforced

* Correctness before feature breadth.
* Explicit separation of responsibilities.
* Dependency injection at the composition root.
* Small application services with testable boundaries.
* Configuration rather than hard-coded runtime assumptions.
* Controlled external-service failures.
* Explicit resource cleanup.
* Structured operational logging without unnecessary document/PII exposure.
* Evaluation-driven retrieval configuration.
* Grounded generation and application-controlled source attribution.
* Tests that exercise real behavior rather than merely reproducing implementation details.
* No unnecessary advanced RAG architecture added without evidence that it was needed.

### Milestone status

**Block 6 is substantially complete.**

The only remaining item is the final execution of the automated E2E test and recording its definitive result. After that, the implementation can move into **Block 7 — Final Documentation**.
