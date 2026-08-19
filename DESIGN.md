# Document Intelligence Service — Design & Decisions

The service uses FastAPI and Pydantic for the fixed API contract, request
validation, and HTTP error mapping. Extraction renders scanned PDFs with
PyMuPDF, recognizes every page with Tesseract, detects `PERSON` spans with
spaCy, converts OCR boxes to PDF coordinates, and compares normalized full names
with `thefuzz`. Ingestion reuses OCR, applies deterministic structure-aware
chunking, creates OpenAI-compatible embeddings, and stores chunks, source
metadata, and vectors in PostgreSQL with pgvector. Question answering combines
pgvector retrieval, local FlashRank cross-encoder reranking, an evidence gate,
provider-neutral generation through LiteLLM, and deterministic citation
verification. Use-case orchestrators depend on application `Protocol`s wired in
a composition root, keeping external dependencies replaceable in tests and all
operational settings environment-overridable.

## Component and sequence views

### `POST /api/extract`

Validate the PDF and submitted names, OCR every page, detect and locate `PERSON`
occurrences, then fuzzy-match complete normalized names. Located occurrences and
qualifying matches remain separate response collections.

![Detailed extraction and fuzzy-matching sequence](docs/assets/extract-request-flow.png)

### `POST /api/ingest`

Assign a unique document ID, OCR and recover structure, create word-safe chunks,
attach source context, batch embeddings, and verify the pgvector write result.

![Detailed document-ingestion sequence](docs/assets/ingest-request-flow.png)

### `POST /api/ask`

Scope and embed the question, retrieve and rerank evidence, abstain when evidence
is weak, and otherwise generate an answer whose citations are verified before
sources are returned.

![Detailed grounded-RAG question sequence](docs/assets/ask-request-flow.png)

Local deterministic stages surround probabilistic dependencies. Coordinates are
normalized before leaving OCR, evidence is approved before generation, and API
sources are constructed after—not by—the LLM.

## Notable decisions and trade-offs

| Decision | Why we chose it | Trade-off / next step |
|---|---|---|
| PyMuPDF + local Tesseract | Keeps OCR local and PDF-coordinate conversion auditable | CPU-heavy; at scale, we could use external vision/LLM processing, trading local compute for cost, latency, privacy, and rate limits |
| Small local spaCy NER | Fast local baseline with `PERSON` spans and direct offsets | Benchmark it against transformer-based NER, especially on noisy scans |
| Normalized `thefuzz.ratio` | Explainable baseline for accents and small OCR errors | Evaluate semantic comparison for nicknames, reordered names, and larger OCR errors, while measuring false positives |
| Deterministic structure-aware chunks | Predictable chunks with whole words and page traceability | Complex layouts may require a layout-aware parser |
| PostgreSQL + pgvector | Closer to production, with durable vector-database support and metadata filtering | More operations than embedded Chroma; benchmark indexing as the corpus grows |
| Remote embeddings + local reranker + LiteLLM | Semantic retrieval, local reranking, and provider flexibility | External calls add latency, cost, quotas, and credential dependencies; keep models and limits configurable |
| Evidence gate + citation verifier | Mechanisms to prevent hallucinations: abstain before generation and verify sources afterward | Citations do not prove claim support; add claim-to-evidence evaluation as the next safeguard |

## Scaling to 1,000+ PDFs/hour

At this volume, ingestion should move from a request-bound pipeline to an
event-driven workflow. The API uploads each PDF once to Amazon S3, creates an
idempotent job, and publishes its S3 key to Amazon SQS. The queue provides
buffering and backpressure; workers can retry safely, while repeatedly failing
documents move to a dead-letter queue.

AWS Lambda can process short, bursty page or small-document jobs concurrently.
For sustained traffic or CPU-heavy OCR/NER that benefits from warm models, the
same container can run on ECS/Fargate and scale horizontally using queue depth,
queue age, CPU, and memory. The Lambda/ECS boundary should be selected from load
tests using cost per processed page, execution time, and cold-start impact—not a
fixed PDF count. After pages are joined in order, embedding calls and pgvector
writes are batched to reduce network and database overhead. The synchronous
endpoint remains suitable for this take-home; a production version would add
asynchronous job submission and status endpoints.

## Failure modes and mitigations

| Failure | Behavior / mitigation |
|---|---|
| Empty, oversized, spoofed, corrupt, protected PDF; bad names/question | Reject before models with 400/413/415/422; inspect bytes with PyMuPDF and close handles in `finally` |
| OCR/NER failure or unlocatable span | Per-page OCR timeout and typed 503; omit/log an unlocatable mention rather than return a false audit box; alert on located/NER ratio |
| Embedding/LLM timeout or malformed output | Bounded retries/timeouts; validate vectors and finish state; invalid upstream response → 502, unavailable dependency → 503 |
| PostgreSQL disconnect or partial write | Pre-ping, connect/statement timeouts, exponential retry, UUID IDs, and exact stored-ID/count verification |
| Irrelevant retrieval, prompt injection, invented source | Explicit-only filters, reranking, evidence gate, content marked untrusted, no LLM on weak evidence, citations resolved only against supplied passages |

## Routing models by query complexity

Today one answer model is configured. A future deterministic router runs **after
retrieval and the evidence gate**: no evidence → no model; one high-confidence
passage plus fact lookup → small/cheap model; comparison, aggregation, multiple
documents/sections, long context, or a narrow reranker-score margin → stronger
long-context model. Both routes receive the same approved evidence and citation
verification. One escalation is allowed for truncation or invalid citations;
otherwise return a controlled error, never an unverified answer. Offline
evaluation sets thresholds using answer correctness, citation precision/recall,
abstention quality, latency, and cost—not model self-assessment.
