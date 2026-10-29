# DECISIONS

Notable decisions and trade-offs. Full context: [DESIGN.md](DESIGN.md), the
[TRD](docs/trds/document-intelligence-trd.md) (ADR-001…011) and
[`docs/adrs/`](docs/adrs/) (ADR-012…015).

## Run it

```bash
uv sync --extra dev && uv run uvicorn app.main:app   # → http://localhost:8000/viewer
docker compose up --build                            # same, in a container
```

`/api/ask` needs `DOCINTEL_LLM_API_KEY` in `.env` (a free Groq key); without it the app
still starts and `/ask` answers `503 llm_not_configured`. Every setting is listed in
`.env.example`. Tesseract must be installed for local runs (the image has it).

## Architecture

- **Hexagonal (ports and adapters).** Use cases depend on `Protocol` ports; each library
  lives in one adapter; adapters are built once in the FastAPI lifespan and injected.
  Domain and application never import FastAPI, Pydantic or a vendor SDK —
  `import-linter` enforces it. *Why:* every engine can be swapped or faked in tests.
  *Cost:* more files and DTO ↔ domain mapping than a 4-endpoint service strictly needs.
- **Deterministic workflow, one LLM step.** The LLM only writes the answer text.
  Names, pages, boxes, scores, the "not found" decision and `sources` are computed by
  code, so everything a compliance reviewer relies on is reproducible.
- **CPU-bound endpoints are sync `def`**, so FastAPI runs them in its threadpool and the
  event loop stays free.
- **The fixed contract is untouched** — no field was added to `app/models/schemas.py`.

## Extraction

- **Every page is rendered at 300 DPI and OCR'd with Tesseract**, page 0 included.
- **Boxes are converted to PDF points once, in the OCR adapter** (`pt = px × 72 / DPI`),
  with the **top-left origin** of PyMuPDF and pdf.js (a bottom-left consumer flips
  `y' = page_height − y − height`). Pages are 0-based. Coordinates rounded to 0.01 pt.
- **Names are located by character offsets, not by searching the text.** Page text is
  rebuilt from the OCR words while recording each word's span; spaCy's PERSON spans
  map back to exactly the words they cover. One box per real occurrence, repeated names
  handled, honorifics (`Dr.`) excluded from name and box.
- **spaCy `en_core_web_lg`, not `sm`.** On the OCR'd samples `sm` reached P 0.91 /
  R 0.95 but reported `Atlas` and `Forbes` as people; `lg` scored P 1.00 / R 0.98 with no
  leaks and needs no torch (ADR-013).
- **Matching = rapidfuzz `max(ratio, token_sort_ratio)` ≥ 0.90 on normalized full
  names** (casefold, accents stripped, punctuation collapsed). Full-string, so
  `María González` ~ `Maria Gonzalez`, word order is tolerated, and substrings don't
  inflate scores. `thefuzz` (suggested) is now a thin wrapper over rapidfuzz.
- **OCR words below a confidence floor are dropped**, so no box is drawn over noise.

## RAG

- **Chunks = OCR layout blocks packed up to 250 embedder tokens**, page-bounded, no
  overlap. A unit that doesn't fit moves whole to the next chunk (paragraph → sentence
  → word), so a chunk can never cut a word, and no chunk exceeds e5's 512-token window
  (ADR-015). No rules tuned to the sample PDFs.
- **IDs = `{sha256(pdf)[:16]}:{chunk_index}`.** A second document can't overwrite the
  first, and re-ingesting the same file is an idempotent upsert (ADR-007).
- **Retrieval = dense (e5) ∪ BM25 → cross-encoder rerank → top 5.** Dense search misses
  exact names and figures; BM25 catches them. BM25 is a pure function computed per
  query over the stored chunks, so there is no index to keep in sync (ADR-014).
- **The LLM decides when the answer is not in the documents.** It gets the five best
  passages and is told to answer only from them, or to say "The answer is not in the
  ingested documents." I first made that call in code, with a cut-off on the reranker
  score, and dropped it after testing: it turned away "Who is the CEO?" although the
  memo names her. Questions that have an answer and questions that don't get
  overlapping scores ("Who wrote the memo?" scores lower than "Who won the 2022 World
  Cup?"), so no cut-off can tell them apart (CR-002). The price is one LLM call per
  question.
- **Sources can't be hallucinated.** Passages are numbered; the LLM cites `[n]`; code
  turns citations into `"file, page n"` from the passages actually sent. Citations of
  passages not sent are dropped; an answer with no valid citation becomes "not found".
  The answer keeps its citations, renumbered so `[1]` is the first entry of `sources`,
  `[2]` the second, and so on, so a reader can see which source backs each sentence.
- **Prompt injection.** Document text is wrapped as delimited data, the LLM has no
  tools, and the viewer renders answers as plain text.
- **Models:** `multilingual-e5-small` (embedder) and `mmarco-mMiniLMv2-L12` (reranker),
  both multilingual so Spanish questions work. The stronger `bge-reranker-v2-m3` took
  21 s per question on CPU; mmarco takes ~1.5 s (ADR-014).
- **LLM = Groq `openai/gpt-oss-120b` through the openai SDK** (any OpenAI-compatible
  endpoint by config; timeouts and backoff retries from the SDK). Groq retired the first
  choice, `llama-3.3-70b-versatile`. gpt-oss cites as `【n】` and puts U+202F inside
  names, so the parser accepts both bracket styles and normalizes spaces.

## Engineering

- **Config:** one `Settings` object, every value `DOCINTEL_*`-overridable; no host,
  model, threshold, DPI or limit hardcoded.
- **Validation at the edge, by content:** `%PDF-` signature, empty, size, page count,
  encrypted/corrupt, malformed `names` — each with its own 4xx `error.code`.
- **Errors:** domain errors → 4xx, infrastructure errors → 5xx, always with
  `request_id`; vendor exceptions are translated inside their adapter.
- **Logging:** structured JSON with event names and `request_id`; names and document
  text are never logged.
- **Tests (~870):** pure domain tests (geometry, alignment, matching, chunking property
  tests, BM25, grounding), use cases on in-memory fakes of every port, adapter tests
  against the real engines, end-to-end through HTTP on the sample PDFs.
- **Evals (`scripts/`), not just tests:** NER P/R vs a hand-labelled golden set; box
  self-check (crop each box, re-OCR, fuzzy ≥ 0.90: 54/54); retrieval hit@1 11/12; answers
  pass^3 15/15 (each question must pass 3 runs in a row) with 0 ungrounded sources.
  Deterministic graders, so an eval run costs nothing but the LLM calls.
- **Docker (bonus):** one container — Tesseract and the models baked in, non-root,
  read-only filesystem, healthcheck — with embedded Chroma on a named volume. A separate
  vector-DB service was deliberately not added: the brief accepts embedded Chroma and the
  `VectorStore` port makes a server one adapter away.
- **Audit viewer (bonus):** `/viewer` renders the PDF with pdf.js, draws the boxes
  (green = matched), and has a tab to ingest and ask.

## Known limitations

- **ALL-CAPS documents defeat the NER.** spaCy relies on capitalization; on a Colombian
  property certificate it returned fragments like `GABRIEL JOSE ANOTACION`. The default
  NER and OCR language are English (`DOCINTEL_OCR_LANGUAGES=eng+spa` and a Spanish
  model are config changes).
- The golden sets are small (5 pages, 15 questions): the numbers show the system fits
  these documents, not that it generalizes. Each new miss should become a golden entry.
- Starlette spools the whole upload before our size check; a hard cap belongs in the
  proxy.
- BM25 per query is O(chunks) — fine here, replaced by a store with native hybrid search
  at scale (DESIGN §5).
- Byte-identical PDFs with different names collapse into one document.
- PyMuPDF is AGPL; pypdfium2 fits the same port if that matters commercially.

## Use of AI tools

I built this with Claude Code (Anthropic) as a pair programmer. I set the architecture
and made the decisions (hexagonal design, offset-based alignment, `lg` over `sm`, hybrid
retrieval with a mandatory reranker, no rules tuned to the samples, embedded Chroma in
Docker); the assistant researched options, ran the spikes and evals, and drafted code,
tests and docs, which I reviewed. Work followed a spec → plan → tests-first → validate
loop (`docs/specs/`, `.claude/plans/`). Every commit passed lint, strict typing,
import contracts and the test suite.
