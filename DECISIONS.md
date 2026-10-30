# Decisions

Notable engineering decisions and trade-offs. This file grows with each slice.

## Summary

- **Every page, boxes in PDF points:** pixels → points with `page.rect.width / pix.width`, so no DPI is hard-coded. Measured on the 3 samples: NER precision 1.0, recall 54/55, boxes within ±2 pt of a hand-checked reference.
- **Boxes by character offsets, not string search:** NER spans and OCR words share one page text, so OCR noise and case never break the lookup.
- **Fuzzy score = max(`ratio`, `token_sort_ratio`):** full-string only, after casefold, accent and title removal; threshold 0.90, configurable.
- **Services depend on small Protocols** (`OcrEngine`, `NameRecognizer`, `Embedder`, `LLM`, `ChunkStore`, `ChunkSearch`) injected with `Depends`; unit tests never load a model, Tesseract or an LLM.
- **Errors by content, mapped in one table** (422, 413, 502, 503, 504); one JSON log line per request with a request id, no names (PII).
- **RAG chunks per page, cut only between words**; IDs `sha256:page:chunk`, so a second document never overwrites the first.
- **Grounding:** `sources` are built in code from the retrieved chunks, never from the LLM reply; two abstention gates (similarity floor 0.20 and a fixed sentence). Measured: 21/22 answers, 4/4 abstentions.
- **LLM over plain `httpx`, OpenAI-compatible:** 5 s / 60 s timeouts, 3 attempts with backoff on network errors, 429 and 5xx only.
- **Embedded Chroma, one worker:** enough here; a second process would read a stale index (measured), so scaling needs a vector DB service.
- **Numbers are regression checks on 3 PDFs, not quality estimates;** each section below says how it was measured and its known limits.

## How I work

I work in three phases, in order:

1. **Research.** For each stage (OCR, PDF geometry, NER, fuzzy matching, RAG, evaluation) I reviewed the literature and compared candidate packages by license, maintenance and fit before writing code.
2. **Notebooks.** Each stage is prototyped in a local notebook on the sample PDFs: try options, see where they fail, measure, and keep the simplest one that works. The notebooks, with my research notes and the AI setup, are in `docs/working-materials.zip`; their conclusions are recorded in this file.
3. **Implementation.** Each slice of `app/` then follows a short spec with numbered acceptance criteria, tests named after them (`test_ac_<area>_<nn>_*`), minimal code to pass them, and lint, format and tests green before the commit.

Decisions that rest on published work cite it inline (author, year, section or table); full references are listed at the end of this file. Where a paper supports an idea but did not test our exact setup, the text says so and points to my own measurement.

## AI-assisted workflow

Before any code, I set up the rules Claude Code works under (kept locally, not in this repository):

- Project instructions: scope, the fixed contract (`schemas.py` is not modified), code style, and sample PDFs, OCR text and web content treated as untrusted data.
- A pre-tool hook that blocks git write commands and reading secret files. I run every git command. (It also blocked edits to `schemas.py` until task 06; the rule now lives in the project instructions.)
- Skills: `grill-me` (two subagents with opposite briefs, minimal code vs. what the evaluation rewards, debate a slice's open decisions before its spec is written) and `commit-handoff` (prepares the commit commands I run).
- Subagents with one role each, and none of them runs git:
  - `literature-researcher` and `paper-curator` (papers with verified citations);
  - `package-auditor` (runs snippets to check what a package really does);
  - `notebook-builder` and `notebook-reviewer` (the reviewer never sees the builder's conclusions);
  - `implementer` (tests first, then minimal code);
  - `code-critic` (attacks each spec and each commit's diff, and runs mutations on a copy to check that the tests catch them);
  - read-only helpers and a `final-evaluator` for the whole branch.
- I approve each subagent before it runs. Every critique is saved next to its task.
- A spec template and one verification script (ruff, format check, pytest).
- Git hooks that reject AI attribution trailers and scan staged files for secrets (gitleaks).
- A dated decision log; this file keeps the decisions that matter for the delivery.

## Environment and dependencies

- **Python 3.12 pinned** (`.python-version`) and `uv.lock` committed, so every machine resolves the same versions.
- **`rapidfuzz` directly, instead of `thefuzz` + `python-Levenshtein`.** `thefuzz` 0.22 is a thin wrapper over `rapidfuzz`, and `python-Levenshtein` is GPL-2.0-or-later and not needed. Same scorers, one layer and one copyleft dependency less.
- **spaCy model as a locked dependency.** `en_core_web_sm` 3.8.0 is pinned by URL in `[tool.uv.sources]`, so its version lives in `uv.lock`. No `spacy download` step: it installs through `pip`, which a uv virtual environment does not include.
- **`dev` kept as an optional extra** (`pytest`, `pytest-cov`, `ruff`), so `uv sync --extra dev` from the README keeps working. `pytest-asyncio` removed: no async tests are needed.
- **CPU-only PyTorch on every platform.** `torch` is pinned to the official CPU index (`download.pytorch.org/whl/cpu`, `explicit = true`), so the lock contains no CUDA packages. Embedding a few chunks with a small model does not need a GPU, installs stay small (also in Docker), and a local GPU stays free for the LLM.
- **`tenacity`** is included for retry policies on external calls (LLM; vector store when it runs as a separate service).
- **ruff with the default 88 columns**, matching the style of the provided stubs, so formatting does not touch files outside each change.

## Configuration

- **Single source of settings** in `app/config.py` (pydantic-settings). Precedence: environment variable, then `.env`, then the default in code. Values are typed (`OCR_DPI=150` arrives as an `int`).
- OCR DPI, language, page segmentation mode and timeout are configurable.
- **The `tesseract` binary is resolved from `PATH`**, like any command-line tool, instead of a configurable path. Linux package managers install it on `PATH`; the Windows installer does not, so the setup step there is to add it. Trade-off: one less setting, but Tesseract must be on `PATH`.
- `.env.example` documents every key. `.gitignore` un-ignores it (`!.env.example`) because the original `.env.*` rule excluded it.

## Fuzzy matching

- **Normalization before comparing:** `casefold`, Unicode NFKD with combining marks removed, apostrophes deleted (so `O'Brien`, `O’Brien` and `OBrien` share one key), other punctuation turned into spaces, and the titles Dr/Mr/Mrs/Ms/Miss/Prof dropped. Titles are one of the sources of name variation listed by Christen (2006, Sec. 2.1); without dropping them, "Dr. Robert Chen" vs "Robert Chen" scores 0.88.
- **Score = max(`fuzz.ratio`, `fuzz.token_sort_ratio`) / 100.** Both are full-string Indel similarities. For person names, edit-distance metrics beat token-based ones (Cohen et al. 2003, Table 2, Census data). `token_sort` handles reversed order ("Gonzalez Maria": 1.0 vs 0.571 with `ratio`); `ratio` handles a typo that sorting would move ("Katherine Dubois": 0.9375 vs 0.50). Taking the best of both orders follows Christen's "Permuted-Winkler" idea (2006, Sec. 3.2); applying it to Indel is my inference, measured on the labeled pairs below. `partial_ratio`, `token_set_ratio` and `WRatio` are not used: they give 1.0 to "Maria" vs "Maria Gonzalez".
- **Threshold 0.90 (the README default), configurable with `FUZZY_THRESHOLD`** and validated to [0, 1]. The function keeps the stub's two-argument signature; `threshold=None` reads the setting at call time.
- **Output:** every pair at or above the threshold, filtered on the raw score and rounded to 4 decimals only for output, sorted by score and then by name. Names are deduplicated by normalized key on both sides (the first spelling is kept), and names that normalize to an empty string are dropped (`ratio("", "")` is 100).
- **Measured on 27 labeled pairs** (`eval/gold_fuzzy_pairs.csv`: 15 same-person variants, 12 hard negatives): recall 12/15 and false-positive rate 4/12, each with a 95 % Wilson interval ([0.55, 0.93] and [0.14, 0.61]), because the Wald interval breaks down at small n (Brown, Cai & DasGupta 2001). Precision and F1 are not reported: they depend on the positive/negative mix I chose, and F1 weighs precision and recall differently by method and threshold (Hand & Christen 2018). These are resubstitution numbers: the same pairs informed the choice of scorer, and Christen (2006) notes that thresholds depend on the data.
- **Known limits:** initials ("J. Anderson"), middle names, two or more OCR errors in one name, and names one letter apart (Mario/Maria) are not resolved; `ø`/`ł` are not folded and `ü` does not become `ue`.

## Person NER

- **spaCy `en_core_web_sm`, label PERSON only**, behind a `NameRecognizer` Protocol, so unit tests use a fake (a lambda) and never load the model. The model is loaded once per name with `lru_cache`, on first use, not at import.
- **Spans per page, `(name, start, end)`.** Box lookup (OCR words) needs character offsets on each page's text, so `find_person_spans(pages)` works page by page. `extract_names(text)` keeps the stub's signature and treats the text as one page.
- **Three filters**, from the error analysis on the samples: a span that crosses a line break, a single word, or ALL CAPS (headers) is not a person name. Only the ALL CAPS filter is configurable (`NER_DROP_ALL_CAPS`), because it depends on the document type; "two words or more" defines a full name and keeps propagation safe.
- **Document-level propagation.** A name found on any page is also marked at its other exact, whole-word occurrences in the same document (never across documents). Within a document the same string rarely changes entity type (Finkel et al. 2005, Sec. 5.1, Table 3), and document-level consistency adds +2.95 F1 on persons while corpus-level adds only +0.09 (Krishnan & Manning 2006, Table 3); the principle goes back to "one sense per discourse" (Gale et al. 1992). Gains depend on the text type (Ratinov & Roth 2009), so I measured it: recall 0.945 → 0.982, no new false positives.
- **Measured on 55 labeled mentions** (`eval/gold_names.csv`, 3 sample PDFs): precision 54/54 = 1.0, recall 54/55 = 0.982. `app/` reproduces the notebook's spans exactly. Same caveat as fuzzy matching: these are the samples that guided the filters.
- **Known limits:** propagation is case-sensitive ("ROBERT CHEN" is not linked to "Robert Chen"); single-word mentions are dropped on purpose; a propagated span partially overlapping a longer spaCy span would give two spans (0 cases in the samples).

## OCR and bounding boxes

- **Bytes in, one open.** `ocr_pages(pdf_bytes)` opens the PDF once with `pymupdf.open(stream=..., filetype="pdf")`: the upload is already in memory, so no temp files. pymupdf still opens an image (a PNG) as a document even with `filetype="pdf"`, so the code also checks `doc.is_pdf`. Empty, non-PDF, image or corrupt bytes raise `InvalidPdfError` (it wraps pymupdf's `FileDataError`), so the endpoint maps it without importing pymupdf. The path-based stubs read the file and delegate.
- **Every page, boxes in PDF points.** Each page is rendered at `OCR_DPI` (300) in grayscale and read by Tesseract behind an `OcrEngine` Protocol (unit tests use a fake). Pixels become points with `page.rect.width / pix.width`, so no DPI is hard-coded (the test runs at 150 DPI to catch that). Words with `conf < 0` or blank text are dropped.
- **Origin is configurable.** Top-left by default, like the image; `BBOX_ORIGIN=bottom-left` flips each word (`y = H - y - h`) for PDF-native consumers. The flip is monotonic, so the union box does not change shape.
- **Boxes by offsets, not string search.** NER spans and OCR words share the same page text, so a name's box is the union of the words its span touches. There is no string comparison to break on case or OCR noise. NER runs once over all pages, so a name found on one page is also boxed on the others.
- **One box per occurrence.** 0 of 54 mentions cross a line (NER drops those), and `ExtractedName` has one box. Edge punctuation stays inside ("Thompson," → about 5 pt wider on 19/54 mentions); the box still contains the name.
- **Measured.** A synthetic scanned PDF (fonts 11/14/24) gives a box inside the text box (±1 pt) with ≥ 0.95 of its width; IoU is not used because the reference is a line box and Tesseract boxes the ink. On the 3 samples: precision 1.0, recall 54/55, every box within ±2 pt of `eval/gold_boxes.csv`, and `app/` matches the notebook prototype exactly (0.0 pt). The miss (Lucas Zimmermann) is an NER miss: OCR reads both words.
- **License note.** pymupdf is AGPL-3.0 (or Artifex commercial). Fine for this take-home; for a closed product, pypdfium2 (Apache/BSD) would replace the renderer.

## Extraction endpoint

- **Thin router, pure pipeline.** `POST /api/extract` reads the upload and delegates to `extract(pdf_bytes, names, engine, recognizer)`, a plain function (no state, so no class) that runs OCR → NER → boxes → fuzzy match. The OCR engine and the name recognizer are injected with `Depends`; tests replace them through `app.dependency_overrides`, so unit tests never run Tesseract or spaCy.
- **`names` validated by FastAPI.** The form field is declared as `Json[list[NamePair]]`, so invalid JSON, a missing field or an empty name returns FastAPI's own 422 before any OCR runs.
- **Errors by content, mapped in one place.** Three domain errors and one status table in `main.py`: `InvalidPdfError` → 422 (empty, not a PDF, an image, corrupt, or password-protected), `DocumentTooLargeError` → 413 (`MAX_UPLOAD_MB`, `MAX_PAGES`), `OcrEngineError` → 503 (Tesseract timeout or missing binary). There is no `%PDF-` magic check: the parser already rejects non-PDFs by content, and the PDF format allows bytes before the header. A password-protected PDF opens without error and fails only when rendered, so `ocr_pages` checks `needs_pass` right after opening; the page limit is checked in the same open, before rendering.
- **Upload limit.** The router reads at most `MAX_UPLOAD_MB` + 1 byte. Starlette has already received the body (spooled to disk above 1 MB) and closes the file after the request, so the limit rejects the upload but does not save the transfer; in production a proxy limit would.
- **Structured logs without PII.** One JSON line per request (method, path, status, ms) and one per extraction (pages, names in, names found, matches), both tagged with a request id taken from `X-Request-ID` or generated, and returned in the response header. Names are never logged. Standard library only.
- **Measured.** On `company_memo.pdf` with the fuzzy notebook's query list, the endpoint returns the 8 mentions on page 0 and the 3 expected matches (integration test, skipped without Tesseract or the spaCy model).

## RAG ingestion

- **Chunks per page, 500 characters, 60 of overlap, cut only between words.** Each page's OCR text is split on whitespace; words are packed until the next one would pass 500 characters, and the next chunk starts with the last whole words that fit in 60 characters.
  *Why:* the README forbids cutting words; chunking per page keeps the page number exact for `sources`; 500 characters is about 75 MiniLM tokens, far below its 256-token limit, so nothing is truncated.
- **This strategy over five alternatives, for robustness rather than a metric.** Compared with paired tests (exact McNemar on hit@1, paired bootstrap of ΔMRR) on 22 questions with labeled pages (`eval/questions.json`, plus 4 with no answer): no overlap, sentences, recursive splitting, whole page, whole document.
  *Why:* none differed significantly (all p ≥ 0.45, every ΔMRR interval contains 0), so the metric cannot choose. Overlap keeps a name that falls on a chunk border ("Jennifer Liu") whole in one chunk, and Chroma's own evaluation finds overlap neutral to slightly positive for this model (78.7 vs 78.5 recall, 250 tokens with 125 vs 0 overlap; Smith & Troynikov 2024). Whole document was the worst (ΔMRR −0.078) and loses the page. Semantic chunking was not tried: Qu et al. (2024) find it does not justify its cost.
- **No OCR text normalization.**
  *Why:* OCR noise degrades RAG (Zhang et al. 2025), but joining hyphens and collapsing whitespace did not change the metrics on our documents; code that changes nothing measurable is not added.
- **Metrics read as regression checks, not as quality estimates.** Reference: hit@1 0.68 [0.47, 0.84], hit@3 0.95, MRR 0.82 [0.71, 0.93].
  *Why:* with 5 pages in total, hit@3 is close to 1 for every strategy and 22 questions only detect large differences; the numbers say "it did not get worse", not how it would do on a real corpus.
- **Measured: `app/` reproduces the prototype.** On the sample pages, `chunk_text` gives the same 12 chunks as the notebook prototype, and retrieval through `store_document_chunks` and `search_similar` ranks all 22 questions exactly as the prototype does.
  *Why:* the notebook is where the strategy was chosen; this check shows the code that ships is that strategy and not a variant of it.
- **`all-MiniLM-L6-v2`, normalized embeddings.**
  *Why:* `bge-small-en-v1.5` scores higher on MTEB retrieval (51.68 vs 41.95; Muennighoff et al. 2023) but tied on our questions, so the change would not be measurable here. Normalized vectors make cosine, dot product and L2 rank the same.
- **Embedding model stored in the collection metadata and checked on reopen.**
  *Why:* MiniLM and bge-small both have 384 dimensions, so switching models without re-ingesting would mix vectors from two models with no error. A mismatch raises `VectorStoreError`.
- **Chroma `PersistentClient`, one per process, one collection, cosine, explicit vectors.** Created with `{"hnsw": {"space": "cosine"}}` and `embedding_function=None`; queries always pass vectors; `score = 1 - distance`.
  *Why:* Chroma's default is squared L2, which is not the score we want to report; without `embedding_function=None`, a text query makes Chroma download its own ONNX model (about 79 MB) and embed with a different model. One client per process avoids reopening the store on each request.
- **IDs `doc_id:page:chunk`, with `doc_id` the SHA-256 of the PDF bytes; `filename` in the metadata.**
  *Why:* the README requires IDs unique across documents; hashing the bytes makes the same PDF map to the same chunks under any filename. A re-scan has different bytes and counts as a new document.
- **Re-ingestion deletes the document's chunks, then adds the new ones.**
  *Why:* Chroma silently drops an `add` whose ID already exists (the old text stays), and `upsert` would leave stale chunks when a new version has fewer of them.
- **`ChromaError` → `VectorStoreError` → 503.**
  *Why:* `ChromaError` is the common base of Chroma's internal, not-found and invalid-argument errors, so one `except` covers them; the endpoint maps domain errors in one table, as `/api/extract` does, without importing Chroma.
- **A PDF with no text returns 200 with `chunks_stored = 0`.**
  *Why:* a blank page is a valid PDF with nothing to index, not a client error. The code skips Chroma there because `add([])` raises `ValueError`, which would become a 500.
- **One uvicorn worker with embedded Chroma.**
  *Why:* measured with two processes on the same path, the reader sees the new `count` (SQLite) but its `query` still uses the old vector index and returns the wrong chunk, with no error. One worker is uvicorn's default; more workers need Chroma as a separate service.
- **No chunking or vector-store package beyond Chroma.**
  *Why:* LangChain text splitters, semchunk, chonkie, fastembed, FAISS, LanceDB, Qdrant and sqlite-vec were reviewed; none saves anything against about 15 lines of chunking, and each adds dependencies (onnxruntime, grpc, pyarrow, langchain-core) or lacks metadata (FAISS).

## RAG answers

- **Two abstention gates: a similarity floor and a fixed sentence from the LLM.** If the best chunk scores below `MIN_SCORE = 0.20`, the service abstains without calling the LLM. Otherwise the prompt tells the model to reply exactly "I don't know based on the documents." when the context does not contain the answer, and the code detects that sentence (case-, quote- and spacing-insensitive). A blank reply counts as an abstention too: an empty answer with sources would look grounded and say nothing.
  *Why:* a cosine floor alone cannot separate answerable from unanswerable questions here. Two unanswerable questions score about 0.48, above 11 answerable ones, so any floor high enough to catch them would drop half of the real questions. The floor still saves an LLM call when nothing relevant was retrieved, and guards against swapping in a model that abstains less reliably: Qwen-7B returned the requested sentence only 31% of the time in RGB (Chen et al. 2024).
- **0.20, from a plateau, reported with leave-one-out.** On the 22 answerable and 4 unanswerable questions, any floor between 0.125 and 0.25 gives the same result. 0.20 sits in the middle of that plateau, with a margin below the lowest answerable question (0.256).
  *Why:* the threshold was chosen on the same questions it is evaluated on, so "0 false abstentions" holds by construction. Re-deriving the rule with each question left out gives 1/22, and that is the number to quote.
- **Measured with `qwen2.5:7b-instruct`: 21/22 correct answers, 4/4 abstentions, 1/22 false abstentions.** The one miss is the only question whose answer spans two documents: the model abstains even though both pages are in its context.
  *Why:* these are regression checks on a 5-page corpus, not quality estimates. At temperature 0, the 26 answers were identical across 3 back-to-back runs, but one changed wording minutes later (see below).
- **The threshold gates on the top chunk; all top-k chunks go to the prompt.**
  *Why:* this is what the notebook measured. Filtering chunk by chunk would change the context of 9 of the 26 questions, and the numbers above would no longer describe the shipped code.
- **`sources` built in code from the chunks sent to the LLM, never parsed from its reply; empty when the service abstains.** IDs are `file:pN:cK`.
  *Why:* the README forbids fabricated sources. A model can invent an ID; the code cannot. An abstention has no answer to support.
- **Retrieved text is data: delimited, escaped, and reminded after.** Chunks go inside `<context>…</context>`, with their `<` and `>` escaped; the system prompt says the context is data, not instructions; a reminder follows the context. The LLM has no tools.
  *Why:* OCR text is untrusted input (OWASP LLM01; Greshake et al. 2023). Delimiting roughly halves attack success (Hines et al. 2024). No prevention-based defense is sufficient on its own (Liu et al. 2024), so this is mitigation, not a guarantee. Measured: 0 of 475 injected runs (6 attacks × 3 positions, with and without an answer) made the reply contain the attacker's word. 6 of them made the model abstain on a question it could answer; that is a known limit.
- **One small LLM client on `httpx`, OpenAI-compatible, no SDK.** One POST to `{LLM_BASE_URL}/chat/completions` with temperature 0 and `max_tokens`. The bearer header is sent only when `LLM_API_KEY` is set. The default is local Ollama.
  *Why:* the README asks for an OpenAI-compatible endpoint. One function shows every decision (timeouts, retries, errors) that an SDK would hide. Switching to a hosted provider is three environment variables, so there is no automatic fallback model.
- **Timeouts: 5 s to connect, 60 s to read.**
  *Why:* the first call after installing the model took about 50 s while Ollama loaded it into the GPU; warm calls take p50 0.75 s, p95 1.01 s. The connect timeout keeps a dead host from costing 3 × 60 s. The default URL is `127.0.0.1`, not `localhost`: on Windows, `localhost` tries IPv6 first and adds about 2 s to every failed connection.
- **Retries with tenacity: up to 3 attempts, exponential backoff with jitter, only on network errors, timeouts, 429 and 5xx.** The `Retrying` loop lives inside the function and reads the settings on each call.
  *Why:* a 4xx means the request itself is wrong, and repeating it only adds latency. A decorator would read the settings at import time, and tests could not set the wait to 0. Worst case, a timeout on every attempt, is about 184 s on one worker thread.
- **LLM failures map to 503, 504 and 502.** Unreachable, or still 429/5xx after the retries → 503. Timed out → 504. Rejected request (4xx) or a reply with no text → 502.
  *Why:* the client can tell "try later" (503), "too slow" (504) and "the upstream answered something unusable" (502) apart. Error messages carry only the status code, never the upstream body or the key.
- **`TOP_K` and `MIN_SCORE` validated at startup.**
  *Why:* `top_k = 0` makes Chroma raise `TypeError`, which would be a 500 on every request. Validation turns it into one clear error when the service starts.
- **Measured: `app/` reproduces the prototype.** On the 26 questions, `app/` builds the same prompts (26/26), retrieves the same chunks with the same scores, abstains on the same 5 questions, calls the LLM 25 times (the floor stops one unanswerable question before the LLM), and returns the same `sources`. One answer changed wording ("London" vs a full sentence, both correct) between two calls with the same request a few minutes apart in the same run. So temperature 0 on Ollama does not guarantee the same text; the evaluation gates (accuracy, abstention) apply instead of exact string equality.
  *Why:* the notebook is where the prompt and threshold were chosen; this check shows the shipped code is that design and not a variant of it.

## Audit viewer and CI

- **Audit viewer: one static page at `/viewer/`, vanilla JS + pdf.js 6.4.299 from cdnjs, as the README suggests.** It sends the PDF to `/api/extract`, renders each page and draws each box at `x × scale, y × scale` with size `width × scale` by `height × scale`.
  *Why:* boxes are PDF points with a top-left origin over the page as PyMuPDF renders it, and pdf.js's viewport has the same size, also for a cropped or rotated page (checked on a test PDF). No build step, no npm and no new Python dependency: `StaticFiles` ships with FastAPI, and the page shares the API's origin, so there is no CORS.
- **Viewer limits.** It needs network access to cdnjs, and the ES module import carries no integrity hash. It assumes `BBOX_ORIGIN=top-left` and says so on the page. Its unit test checks that the page is served with the pinned pdf.js and calls `/api/extract`; box alignment was checked by eye on the samples.
- **Ask page at `/viewer/ask.html`: ingest PDFs and ask questions from the browser.** Plain JS on top of `/api/ingest` and `/api/ask`, served by the same mount; no backend change. Sources are shown as file, 1-based page and chunk; an empty `sources` list is shown as an abstention.
- **CI on GitHub Actions: ruff, format and pytest on every push and PR.** The runner is pinned to `ubuntu-24.04`, actions are pinned by commit SHA to releases at least two weeks old, the token is read-only, and `uv sync --locked` fails if `uv.lock` is out of date. Tesseract comes from apt, so the OCR and extraction end-to-end tests run; the RAG tests skip (no cached embedding model, no LLM).
  *Why:* GitHub recommends pinning actions to a full commit SHA. A fixed runner keeps the Tesseract version from changing silently: CI gets 5.3.4 from Ubuntu while development used 5.4, and `tesseract --version` plus `pytest -rs -v` in the log make any difference visible.

## Use of AI tools

- Claude Code (Anthropic) was used as a pair-programmer: researching options, drafting code and tests, and reviewing. The author reviewed and ran every change, owns every line, and made every commit.
- The evaluation labels (`eval/gold_names.csv`) start from the NER output and were corrected by me against each page image: 3 missed mentions added with their page and line, and the result checked against an independent count of surnames in the OCR words.
- The box reference (`eval/gold_boxes.csv`) comes from the notebook prototype, checked against the page images, plus one box built by hand from its two OCR words; it is not generated from `app/`, so the test does not compare the code with itself.

## References

- Brown, L. D., Cai, T. T., & DasGupta, A. (2001). Interval estimation for a binomial proportion. *Statistical Science*, 16(2), 101–133.
- Chen, J., Lin, H., Han, X., & Sun, L. (2024). Benchmarking large language models in retrieval-augmented generation. *AAAI 2024*.
- Christen, P. (2006). *A comparison of personal name matching: Techniques and practical issues*. Technical Report TR-CS-06-02, The Australian National University.
- Cohen, W. W., Ravikumar, P., & Fienberg, S. E. (2003). A comparison of string metrics for matching names and records. *KDD Workshop on Data Cleaning and Object Consolidation*.
- Finkel, J. R., Grenager, T., & Manning, C. (2005). Incorporating non-local information into information extraction systems by Gibbs sampling. *ACL 2005*.
- Gale, W. A., Church, K. W., & Yarowsky, D. (1992). One sense per discourse. *DARPA Speech and Natural Language Workshop*.
- Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M. (2023). Not what you've signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection. *AISec 2023*.
- Hand, D., & Christen, P. (2018). A note on using the F-measure for evaluating record linkage algorithms. *Statistics and Computing*, 28(3), 539–547.
- Hines, K., Lopez, G., Hall, M., Zarfati, F., Zunger, Y., & Kiciman, E. (2024). Defending against indirect prompt injection attacks with spotlighting. arXiv:2403.14720.
- Krishnan, V., & Manning, C. D. (2006). An effective two-stage model for exploiting non-local dependencies in named entity recognition. *COLING-ACL 2006*.
- Liu, Y., Jia, Y., Geng, R., Jia, J., & Gong, N. Z. (2024). Formalizing and benchmarking prompt injection attacks and defenses. *USENIX Security 2024*.
- Muennighoff, N., Tazi, N., Magne, L., & Reimers, N. (2023). MTEB: Massive Text Embedding Benchmark. *EACL 2023*.
- OWASP (2025). LLM01:2025 Prompt Injection. *OWASP Top 10 for LLM Applications*. https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- Qu, R., Tu, R., & Bao, F. (2024). Is semantic chunking worth the computational cost? arXiv:2410.13070.
- Ratinov, L., & Roth, D. (2009). Design challenges and misconceptions in named entity recognition. *CoNLL 2009*.
- Smith, B., & Troynikov, A. (2024). *Evaluating chunking strategies for retrieval*. Chroma technical report. https://www.trychroma.com/research/evaluating-chunking
- Zhang, J., et al. (2025). OCR hinders RAG: Evaluating the cascading impact of OCR on retrieval-augmented generation. *ICCV 2025*. arXiv:2412.02592.
