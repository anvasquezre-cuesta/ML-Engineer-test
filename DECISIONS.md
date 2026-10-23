# DECISIONS

Engineering decisions, why I made them, and what they cost. Numbers are measured on the three sample PDFs (5 pages, 55 hand-labelled person mentions in `tests/fixtures/expected_names.json`) on a Windows laptop with Tesseract 5.4.0; `scripts/evaluate_extraction.py` and `scripts/calibrate_similarity.py` reproduce them.

## Contract

- **`app/models/schemas.py` is unchanged in shape.** Field descriptions were added (`BoundingBox` documents its top-left origin and units); two new models (`CheckStatus`, `ReadinessResponse`) serve a new endpoint. `tests/unit/test_schema_contract.py` compares every original model against a frozen copy of the skeleton's JSON schema and fails on any rename, removal, type change or new required field.
- **`GET /health` returns exactly `{"status": "ok"}`**; dependency checks live on a new `GET /health/ready` instead of changing that body.
- **`IngestResponse` stays `{status, chunks_stored}`**; the `doc_id` is logged rather than added, to keep the graded shape exact.

## OCR and coordinates

- **PyMuPDF renders, Tesseract `image_to_data` reads.** It gives word boxes, confidences and `(block, paragraph, line)` keys, which name-to-box mapping needs. PDFs are opened from memory (`stream=`), every page from index 0; no temp files.
- **Boxes in PDF points, top-left origin:** `pt = px × 72 / DPI`, applied by one pure function to every engine's output. Native (bottom-left) PDF space is `page_height − y − height`, documented on the schema.
- **300 DPI by default.** Measured with the `lg` model: 150, 200 and 300 DPI all find 55/55, mean confidence 95.2–95.3, OCR 3.8 / 4.8 / 7.4 s for the 5 pages. 300 costs 95 % more than 150 here; I keep it as the safe default for unknown scans, and `OCR__DPI=150` is the first lever for throughput (see DESIGN.md). `psm 3` and `psm 6` gave identical results.
- **Raw RGB between renderer and OCR** (no PNG encode/decode per page); failures and a per-page timeout raise `OCRFailed` → 503.
- **Not handled:** rotated pages (detected and logged), names hyphenated across lines.

## Names: NER and boxes

- **NER per OCR line.** Whole-page text let spaCy merge a heading with the next line into one "person"; per-line input makes that impossible. Cost: a name wrapped across two lines is not found (none in the samples). Lines go to spaCy in one batch, with only the `ner` component loaded (it does not share `tok2vec`; same entities, 0.07 s for all 5 pages).
- **Offset map.** Each line's text is built from OCR words with each word's character span; an entity's box is the union of the words its range **overlaps** (not exact match), so `Al-Rashidi` and `Foster):` resolve correctly.
- **`en_core_web_lg`**, installed as a locked wheel (`uv sync` installs it; `spacy download` needs pip, which uv environments lack):

  | Model | Precision | Recall | Missed |
  | --- | --- | --- | --- |
  | `en_core_web_sm` | 1.000 | 0.964 | Elizabeth Park, Lucas Zimmermann (read as places) |
  | `en_core_web_md` | 1.000 | 0.982 | Elizabeth Park |
  | `en_core_web_lg` | 1.000 | **1.000** | — |

  Cost: ~400 MB instead of 12 MB. `NER__MODEL` switches it; `PERSON` and `PER` labels both count, so a multilingual model drops in.
- **Entity cleaning moves the character range with the text** (bullets, titles such as "Dr.", trailing punctuation). spaCy once tagged `- Jennifer Liu`; trimming only the text would have kept the bullet inside the box. Titles are outside every box.
- **Precision filters (ALL CAPS, single token) are guards, not load-bearing:** with `lg` the result is 55/55 with or without them. They stay, switchable, for weaker models and unseen layouts.
- **Punctuation that Tesseract glued to a word stays in the box** (`Hernandez,`). Shrinking by character count could clip letters; a reviewer prefers an extra comma.

## Fuzzy matching

- **Normalise, then `token_sort_ratio`.** casefold, NFKD accent stripping, an explicit fold for letters NFKD cannot decompose (`Ł`, `ø`, `æ`…), apostrophes deleted, other punctuation to spaces. Measured: `María García` vs `Maria Garcia` 0.91 raw → 1.00; `O’Brien` vs `OBrien` 0.56 → 1.00; `Łukasz` vs `Lukasz` 0.42 → 1.00.
- **Full-string, order-insensitive scorer.** `token_set_ratio` and `partial_ratio` score `Jennifer` vs `Jennifer Liu` at 1.00 (the substring trick); `token_sort_ratio` gives 0.80.
- **Threshold 0.90, every pair above it returned with its score.** OCR noise (`Rlchard Hernandez`, 0.94) and a different person (`Elizabeth Park` vs `Parker`, 0.93) cannot be separated by string similarity, so the reviewer sees the score. One row per distinct pair: `FuzzyMatch` has no location, and each occurrence keeps its own box in `extracted_names`.

## RAG

- **Chunks: 150-word windows, 30 overlap, never across pages.** Whitespace splitting cannot cut a word; sample pages hold 129–149 words, so each source cites one exact page.
- **Input length measured, not assumed:** the real tokenizer gives 1.27–1.51 word pieces per word (densest page 204 of the model's 256); every truncated chunk is logged.
- **IDs `{sha256(file)}:{page}:{chunk}`**; replace = **upsert, then prune** stale IDs, so a crash never leaves a document with no chunks and re-ingest is idempotent.
- **Grounding enforced by code, with two calibrated thresholds** (10 questions):

  | | Best-match similarity |
  | --- | --- |
  | 5 answerable questions | 0.373 – 0.590 |
  | 5 unanswerable questions | 0.000 – 0.291 |

  Below **0.33 on the best match** the answer is a fixed "not found" and the LLM is never called. Chunks from **0.30** enter the prompt, because the page holding "When is the next board meeting?" scored 0.325 behind a page full of the word "meeting" (0.574). The margin is thin and fitted on 10 questions; both are config, and every request logs its similarities for recalibration.
- **`sources` only from retrieved metadata** (`file.pdf#page=N`, the 1-based PDF open parameter), cleared when the model itself answers "not found"; the prompt treats passages as data, not instructions.
- **Chroma by default, Qdrant behind the same Protocol** (`RAG__VECTOR_STORE=qdrant`). One contract test suite runs on both.
- **LLM: any OpenAI-compatible endpoint**, default local Ollama with `llama3.2:1b` so graders need no key. Timeouts and retries from config; failure → 503. Default URL `127.0.0.1`, not `localhost`: Ollama listens on IPv4 only and the IPv6 attempt cost 2.08 s per new connection (first answer 3.9 s → 0.66 s).
- **Known limit of the 1B model:** retrieval was right on all 7 test questions, yet it named the wrong Q4 presenter once and declined a question whose answer was in the passage. `LLM__MODEL=llama3.2` (3B) or a hosted model is a config change.

## Architecture and practices

- **Protocols for every external capability** (`PdfRenderer`, `OCREngine`, `NERModel`, `NameMatcher`, `Chunker`, `Embedder`, `VectorStore`, `LLMClient`); services import no library. `app/container.py` is the only place that chooses adapters; `create_app(settings, services_factory)` lets tests run the real wiring with fakes.
- **Thin `def` routers:** CPU-bound work runs in FastAPI's thread pool; routers parse, call one service, map the result.
- **One `pydantic-settings` object**, every host, port, model, threshold, timeout, DPI and limit overridable by environment (`.env.example` lists all).
- **Validation by content and size:** `%PDF-` at byte 0 (415 otherwise), empty/corrupt/encrypted 422, oversized 413, rejected **before** the body is spooled (`Content-Length`, or counted for chunked uploads), page limit 413, malformed `names` 422.
- **Every error is `{"detail", "request_id"}`**, including validation errors (without echoing input), 404/405 and crashes (no traceback). Structured JSON logs carry the request ID on every line and never names or document text.
- **Readiness separate from liveness:** `/health/ready` checks OCR, vector store, models (critical → 503) and the LLM (non-critical → "degraded").

## Testing

- Fakes (not mocks) for each Protocol; a test per trap in the brief, mapped in `tests/README.md`; a golden test (55/55 on the real pipeline); every HTTP error path in one table; the extract → ingest → ask path with fakes and against real services. 300+ tests, ~98 % branch coverage, 90 % enforced; integration tests skip cleanly when Tesseract, a model or Ollama is missing.

## Bonus

- **Audit viewer** at `/viewer` (pdf.js draws the API's boxes over the page; checked in headless Chromium at two zoom levels, 55/55 boxes on the names).
- **Containers:** CPU-only image (torch from the CPU index on Linux, 15 NVIDIA packages avoided), models baked in, non-root, offline; compose with an isolated Qdrant and Ollama.
- **Qdrant adapter** with retries for transient errors.

## Use of AI tools

> **Draft for Luis to confirm and rewrite in his own words before submitting.**

- I used Claude (Anthropic) through Claude Code as a pair programmer for this take-home. It analysed the brief, proposed the architecture and roadmap, wrote most of the code, tests and documents in small, reviewed steps, and ran the measurements quoted here (OCR settings, NER model comparison, fuzzy-scorer behaviour, similarity calibration, latency).
- I decided the scope and order of the work, labelled and confirmed the 55 golden mentions, chose the local model, reviewed each step and its commit, and asked for evidence (real runs, screenshots, measurements) before accepting a claim.
- I can explain and modify every file.
