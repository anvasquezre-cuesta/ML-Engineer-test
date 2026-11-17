# Design — Document Intelligence Service

## 1. Scope and components

The service accepts scanned PDFs, locates person names for audit, and answers
questions over ingested text. The fixed API contracts are in
`app/models/schemas.py`. FastAPI routers validate requests and translate errors;
services contain the orchestration and accept injectable dependencies.

```text
React + PDF.js ──► Nginx ──► FastAPI
                              ├─► OCR + spaCy ─► boxes + fuzzy match
                              ├─► chunker + local embeddings ─► Qdrant + SQLite
                              └─► verified retrieval ─► Gemini / OpenAI
```

OCR, NER and embeddings use supervised subprocesses so CPU work does not block
the API event loop. Their concurrency, queues and deadlines are bounded. Qdrant
stores embeddings and OCR fragment text; SQLite stores ingestion metadata, page
counts and recovery state, **not** PDF or OCR text. The embedding model is the
pinned CPU `sentence-transformers/all-MiniLM-L6-v2` revision; it is verified
locally and is the same for document and question vectors. English spaCy and
Tesseract are the configured baseline; other languages need validation.

## 2. Request sequences

**Extract:** `POST /api/extract` validates multipart input → renders and OCRs
every physical page → NER detects people → page-local OCR offsets and geometry
locate each safely mappable span → fuzzy-match full extracted names against the
requested names → return PDF-point boxes with **zero-based** page indices.
Unmappable spans are omitted rather than given invented boxes. Optional repeated
name recovery uses already-located NER names and OCR words; it is off by default.
The separate React frontend calls `/api/extract` through Nginx and renders the
selected PDF in the browser. Stages load automatically after checking the PDF and
final result; Compose supplies an internal proxy credential without asking the
user. The preview retains only the latest PDF and overlays in backend memory,
with bounds and expiry. The local proxy is not user authentication.

**Ingest:** `POST /api/ingest` validates and hashes a PDF → records a new
document and attempt in SQLite → OCRs all pages, including empty ones → splits
each page at word boundaries into up to 128 tokens with up to 32 tokens of
overlap → embeds nonempty chunks → writes uniquely identified points to Qdrant
→ verifies the writes → marks the attempt completed. The Qdrant collection has a
reserved manifest tying it to the ledger and embedding revision. The same PDF
ingested twice deliberately creates two independent documents; the hash supports
analysis, not deduplication.

**Ask:** `POST /api/ask` validates the question → embeds it → searches Qdrant
under the collection lock → checks candidate identities, page metadata and
`completed` state against SQLite → selects bounded context → calls the configured
provider → verifies that each internal citation ID belongs to a selected chunk
and its quoted text occurs exactly there → returns the answer and source strings
with **one-based** page numbers. If retrieval succeeds but finds no eligible
context, or the model cites nothing, the service abstains. A missing ledger or
unavailable dependency is an error, not proof that the corpus is empty.

## 3. Choices, limits and failure handling

- **OCR/NER:** Tesseract and spaCy run locally and keep page-local text offsets;
  OCR noise, small-English-model recall and unusual rotations still need human
  review. Name recovery can improve recall but can introduce false matches.
- **Retrieval and grounding:** normalized embeddings with Qdrant provide
  semantic ranking, not a relevance guarantee. Literal quote checks prevent
  fabricated quote text but do **not** prove that a quote entails the answer.
  Exact matching can reject a legitimate answer when OCR spelling or whitespace
  differs. The prompt treats document text as untrusted data, but is not a
  guarantee against prompt injection. Sources are for inspection, not proof.
- **Consistency:** SQLite and Qdrant are not a distributed transaction. An
  attempt is not queryable until completed; uncertain writes are recorded for
  scoped cleanup. A local file lock coordinates cooperating processes on the
  same host. Do not share this ledger across hosts or network filesystems and
  do not assume protection against unrelated Qdrant administrators/writers.
- **Capacity and failures:** upload/body/page/token limits, bounded admissions
  and deadlines reject excess work. Read retries are bounded. LLM connection
  failures and selected 5xx responses have configurable bounded retries; a 5xx
  may still have incurred cost. `429`, read/write timeouts and invalid generated
  content are not automatically retried. Failures return controlled HTTP errors;
  partial writes are not described as a successful rollback.
- **Privacy:** generation is disabled by default and external providers require
  explicit configuration. Questions and retrieved excerpts leave the host when
  a provider is used. Keys are excluded from workers and document contents are
  not intentionally logged; privileged operators can inspect environment
  variables. The API has no tenant isolation or user authentication, so it must
  not be exposed to untrusted users. The preview cannot revoke downloaded copies
  or promise secure memory erasure.

## 4. Scaling proposal — not implemented or benchmarked

For this illustrative estimate, assume that **each of the 1,000 PDFs/hour has
two pages**, like the two-page examples; that is about **0.278 PDFs/second** or
2,000 pages/hour. Let `T₂` be the measured mean processing time in seconds for
a representative two-page PDF. A first capacity estimate at 70% utilization
is `ceil(0.278 × T₂ / 0.7)` worker slots, before peak and failure headroom.
This is a sizing formula, **not** a claim that the current implementation meets
the target. Other page counts or workloads require their own measurements and
capacity estimates. Benchmark representative PDFs and p95 latency first.

For multiple hosts, replace the local ledger/locks with a shared transactional
store, durable queue and explicit leases/fencing. Store uploaded PDFs in a
private object store; make jobs idempotent per attempt and chunk, and use a
transactional outbox/reconciliation protocol for Qdrant writes. Isolate and scale
OCR and embedding workers independently; batch where measurement supports it.
Bound queues and apply per-tenant admission, retry/dead-letter policies, quotas,
metrics and alerts. Add access control, encrypted storage, retention policies and
an audited document lifecycle before multi-tenant deployment. Distributed
exactly-once delivery is not assumed.

## 5. Model routing proposal — not implemented

Keep a single verified retrieval and citation contract. A policy could use a
cheap local **heuristic**, such as query length, number of required fragments and
whether a multi-step comparison is requested, to select an approved lower-cost
hosted model or a stronger hosted model. Routing would be opt-in, constrained by
privacy, latency, quota and budget; no silent provider fallback. Evaluate answer
and citation quality on an annotated set, measure latency/cost and record only
non-sensitive routing metadata. Do not treat query length or embedding score as
a guarantee of difficulty or truth.

## 6. Verification and remaining work

Unit/integration tests cover contracts, resource limits and simulated dependency
failures. Isolated E2E checks exercise OCR, embeddings, HTTP, SQLite and Qdrant;
Gemini has also been exercised with synthetic documents. The 25-question Gemini
sample predates the latest prompt adjustment and is not a general accuracy estimate. The HTTP retry and
OpenAI-compatible URL tests use simulated transport. A real OpenAI-compatible
endpoint, broader multilingual/OCR quality and distributed concurrency remain
unvalidated. Full commands and observed results are in `docs/TEST_LOG.md` and
`docs/EVALUACION_FUENTES_RAG.md`.
