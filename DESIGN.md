# Document Intelligence Service — Design

## LLM Configuration and Deployment

The service was developed and validated locally using Ollama with Llama 3, which allows the complete RAG workflow to be tested without requiring paid external LLM API access.

LLM configuration is centralized in the `app/config.py` module using environment-overridable application settings. The configuration includes the LLM provider, model, base URL, API key, temperature, timeout, and retry policy. The local defaults use Ollama with Llama 3.

The implementation nevertheless follows the assignment requirement that the LLM use an OpenAI-compatible endpoint with a configurable base URL and API key. In an evaluation or deployment environment, the evaluator can override the relevant `APP_*` environment variables—for example, `APP_LLM_PROVIDER`, `APP_LLM_MODEL`, `APP_LLM_BASE_URL`, and `APP_LLM_API_KEY`—to point the service to an evaluator-provided OpenAI-compatible endpoint. No modification to `app/config.py` or the RAG application logic is required.

Therefore, the same RAG implementation can be validated locally with Ollama/Llama 3 and deployed or evaluated with another OpenAI-compatible LLM endpoint by changing configuration rather than application code.

## 1. Architecture and Component View

The service is a FastAPI application with thin HTTP routers, application services containing business logic, and isolated infrastructure integrations.

```text
Client
  │
  ▼
FastAPI Routers
  │
  ├── /extract ──► ExtractionService
  │                  ├── OCRService ──► PyMuPDF + Tesseract
  │                  ├── NERService ──► spaCy
  │                  ├── BoundingBoxService
  │                  └── FuzzyMatchService
  │
  └── /ingest ──► IngestionService
       /ask ─────► RAGService
                      ├── TextChunker
                      ├── EmbeddingService
                      ├── VectorStoreService ──► ChromaDB
                      └── LLMProvider ──► Ollama/Llama 3
```

Dependencies are assembled in `app/dependencies.py` and injected into services. `RAGService` depends on the application-level `LLMProvider` Protocol rather than directly on Ollama. Routers remain responsible for HTTP concerns; business logic can therefore be tested independently of HTTP.

Configuration is centralized in Pydantic Settings and can be overridden through `APP_*` environment variables.

### Extraction sequence

```text
PDF upload
   → validate content/size
   → render every PDF page
   → Tesseract OCR with word coordinates
   → spaCy PERSON detection
   → map entity spans to OCR words
   → convert coordinates to PDF points
   → fuzzy-match normalized names
   → response
```

### RAG sequence

```text
PDF
 → validation → OCR → page text → word-safe chunks
 → embeddings → ChromaDB

Question
 → embedding/similarity retrieval (top_k=12)
 → retrieved context + metadata
 → grounded prompt
 → configured LLM
 → answer + sources derived from retrieval metadata
```

The RAG prompt instructs the model to use only retrieved context, refuse when evidence is insufficient, and treat document content as data rather than instructions.

---

## 2. Technology Choices and Trade-offs

| Technology            | Role                           | Trade-off                                                                                                                |
| --------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| FastAPI               | HTTP API                       | Lightweight and well suited to typed Python services                                                                     |
| PyMuPDF               | PDF rendering/validation       | Local dependency, but appropriate for PDF processing                                                                     |
| Tesseract             | OCR                            | Open-source/local, but OCR quality depends on document quality                                                           |
| spaCy                 | PERSON NER                     | Simple and explainable; model accuracy is not guaranteed for difficult OCR                                               |
| `thefuzz`             | Name matching                  | Simple full-string similarity; less sophisticated than entity-resolution systems                                         |
| sentence-transformers | Embeddings                     | Strong general-purpose local embeddings without external API dependency                                                  |
| ChromaDB              | Vector store                   | Embedded/local storage is appropriate for the time-boxed assignment; distributed storage would be needed at larger scale |
| Ollama/Llama 3        | Local LLM                      | No API cost during development; latency and answer quality depend on local resources/model                               |
| LangChain components  | Chunking/integration utilities | Used selectively rather than adopting LangChain as the application architecture                                          |

The RAG design deliberately does not add hybrid search, reranking, query rewriting, agents, or multi-query retrieval. Evaluation showed that increasing `top_k` from 5 to 12 exposed relevant evidence for a missed question, so the simpler solution was preferred over adding retrieval complexity without evidence that it was necessary.

---

## 3. Scaling to 1,000+ PDFs/hour

The current implementation is intentionally a local, synchronous take-home design. Embedded Chroma and local processing are sufficient for the assignment and are not intended to represent the final architecture for 1,000+ PDFs/hour.

At that scale, I would separate the API/control plane from asynchronous document processing:

```text
Clients
   │
   ▼
Stateless API
   │
   ├── Object Storage ──► original PDFs
   │
   └── Durable Queue
          │
          ▼
    Ingestion Workers
      ├── OCR workers
      ├── chunking
      ├── embedding workers
      └── vector-store writes
                   │
                   ▼
            Distributed Vector DB

Question API
   │
   ▼
Retrieval Service
   │
   ▼
LLM Service
```

Key changes would be:

* durable object storage instead of relying on local temporary files;
* a durable queue for back-pressure and retries;
* horizontally scalable OCR/embedding workers;
* batched embedding and vector writes;
* a distributed/managed vector database;
* stateless API instances behind a load balancer;
* idempotent document IDs and ingestion jobs;
* dead-letter handling for repeatedly failing documents;
* metrics for queue depth, throughput, latency, OCR failures, embedding latency, and retrieval quality.

The exact worker count would be determined from measured OCR and embedding throughput rather than assumed in advance.

---

## 4. Failure Modes and Mitigations

| Failure                       | Mitigation                                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Invalid/empty/oversized PDF   | Validate content, size, and readability before processing                                                      |
| OCR failure                   | Propagate failure; do not silently return incomplete extraction                                                |
| Poor OCR / missed name        | Preserve OCR coordinates and test representative noisy names                                                   |
| Incorrect name matching       | Unicode normalization, case folding, punctuation normalization, full-string similarity, configurable threshold |
| Vector-store failure          | Translate to controlled service error; API returns 503                                                         |
| LLM timeout/failure           | Configurable timeout and retries; API returns controlled 502 after retries                                     |
| Empty retrieval               | Return an unavailable-answer response without calling the LLM                                                  |
| Hallucinated sources          | Sources are generated from retrieved metadata, not from LLM output                                             |
| Prompt injection in documents | Retrieved content is explicitly treated as data, not instructions                                              |
| Temporary-file leak           | Explicit cleanup in `finally` blocks and context managers                                                      |
| Duplicate vector IDs          | UUID4 identifiers generated for every chunk                                                                    |
| Large-scale ingestion failure | At scale, use queue retries, idempotency, back-pressure, and dead-letter handling                              |

The current local Chroma deployment does not add network-style retries because it is an embedded/in-process component. The abstraction can be extended if the vector store becomes a remote service.

---

## 5. Query-Complexity Model Routing

If multiple LLMs were available, I would route requests according to the complexity of the question rather than selecting a model arbitrarily.

A lightweight routing stage could classify queries using signals such as:

* simple factual lookup versus multi-step reasoning;
* number of retrieved documents/chunks required;
* ambiguity of the question;
* required reasoning depth;
* context size.

For example:

```text
Question
   │
   ▼
Complexity classifier
   │
   ├── Simple factual lookup ──► smaller/faster model
   │
   └── Complex/ambiguous reasoning ──► larger model
```

The router should also have a fallback path. If retrieval confidence is low, the question is ambiguous, or the smaller model cannot produce a sufficiently grounded answer, the request can be escalated to the larger model.

Routing should be evaluated against the same golden dataset used for RAG evaluation, measuring groundedness, answer correctness, latency, and cost. The goal would be to reduce cost and latency without degrading answer quality.

This is a proposed scaling strategy, not functionality implemented in the current take-home.

---

## 6. Testing, Evaluation, Safety and Observability

Engineering tests are separated into unit, integration, and E2E tests. The final regression suite contains 46 automated tests, with the real E2E workflow deselected from the normal regression run because it depends on the locally running OCR, embeddings, ChromaDB, and Llama 3 components. The E2E workflow can be executed separately against those real components.

RAG evaluation is treated separately from software testing. Representative questions were used to check retrieval relevance, answer correctness, unavailable-answer behavior, groundedness, and source correctness. The `top_k=5` retrieval failure that led to `top_k=12` is an example of an evaluation-driven design decision.

Safety controls include upload/request validation, context-only generation, unavailable responses when evidence is insufficient, treating document text as data rather than instructions, and application-controlled source attribution.

Observability uses structured logging through standard Python logging with contextual fields such as document ID, operation status, duration, retrieved chunk IDs, provider/model, and failure type. Full documents, prompts, questions, and generated answers are not logged.

---

## 7. Scope and Limitations

The implementation intentionally prioritizes a correct and testable core over infrastructure complexity. Embedded ChromaDB, local Ollama, and synchronous processing are therefore deliberate take-home choices.

Known limitations include OCR/model accuracy, simple vector retrieval without reranking or hybrid search, dependence on Llama 3 generation quality, local vector-store persistence, and the absence of authentication or distributed production infrastructure.

For a production deployment, the scaling architecture described above would be introduced based on measured workload characteristics rather than prematurely adding infrastructure to the take-home solution.

## 8. Bonus Features

### Docker and Docker Compose

The service includes Docker and Docker Compose configuration as a deployment bonus. The Dockerfile packages the FastAPI application together with its Tesseract OCR runtime dependency, while Docker Compose provides a reproducible application configuration and persistent storage for ChromaDB through a named volume.

The containerized application was validated by rebuilding the image with the current application code and starting it through Docker Compose. The `/health` endpoint returned `200 OK`, and the `/audit` endpoint successfully served the browser-based audit viewer from the container.

Docker is treated as the deployment layer rather than as part of the application architecture. The application services and their dependency boundaries remain unchanged between local and containerized execution.

### Audit Viewer

A lightweight browser-based audit viewer was implemented as a bonus using Vanilla JavaScript and PDF.js. The viewer submits a PDF and candidate names to the existing `/api/extract` endpoint, renders the original PDF in the browser, and overlays the bounding boxes returned by the extraction service.

The viewer intentionally remains a thin client. OCR, PERSON NER, coordinate conversion, bounding-box calculation, and fuzzy matching remain responsibilities of the backend. PDF.js is used only for browser-side PDF rendering and visualization.

The viewer was manually validated against a real sample PDF, confirming that the returned bounding boxes aligned with the detected names in the rendered document.

This provides a practical visual audit of the extraction results while avoiding duplication of document-processing logic in the frontend.
