# ML Engineer Take-Home — Document Intelligence Service

Build, from scratch, a small production-quality service that extracts person
names (with their locations) from scanned PDFs, fuzzy-matches them against a
provided list, and answers questions about ingested documents using RAG
(Retrieval-Augmented Generation).

The four endpoints are implemented. The reviewer quick start below is followed by
the original exercise and more detailed operational notes. `DESIGN.md` and
`DECISIONS.md` explain the implementation and trade-offs.

## Reviewer quick start

**Requirements:** Docker Engine with Compose, `make`, Python 3 and `curl`.
The first image build downloads dependencies and the pinned embedding model; it
may take several minutes and needs network access. The image runs on CPU.

```bash
# One command: approve external use, enter your Gemini key privately,
# build the images and start the application, frontend and Qdrant.
make quickstart

curl --fail http://localhost:8000/health
```

`make quickstart` creates `.env` only if it does not already exist, asks for
explicit consent, and reads your API key without echoing it from an interactive
terminal. It creates a mode-`0600` file, then runs `docker compose up --build -d`.
An existing `.env` is neither read by the setup helper nor changed; Compose uses
it as-is, including a disabled provider if that is how it was configured.
Re-running Compose can recreate this project's services: do not run it against
an existing deployment you do not intend to change. The key is not embedded in
the image or YAML, but privileged Docker/host users can inspect the environment.

Get your own key in [Google AI Studio](https://aistudio.google.com/app/apikey).
The recommended model is **`gemini-3.5-flash-lite`**, which was used in the
recorded synthetic evaluation. Google lists a free tier for this model, but
availability, regions, limits and billing can change; check
[pricing](https://ai.google.dev/gemini-api/docs/pricing) and your project quota.
The free tier may use submitted content to improve Google's products: consult
Google's current terms and never send sensitive documents without authorization.

Without `make`, the same interactive setup and startup can be run as one command:

```bash
python3 scripts/setup_env.py --gemini && docker compose up --build -d
```

For a configuration with generation disabled, use `make setup` and choose `d`,
then `make up`. Alternatively, create the file manually **without overwriting an
existing one**:

```bash
(umask 077; test ! -e .env && test ! -L .env && cp -n .env.example .env)
# Edit .env privately; do not put a key in a shell command or commit the file.
```

For Gemini, set `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash-lite`,
`LLM_API_KEY` to your private key and `LLM_ALLOW_EXTERNAL=true`. The default is
`disabled`: extraction and ingestion work without an external LLM, but valid
`/api/ask` requests return `503` until a provider is configured. An existing
container must be deliberately recreated after configuration changes.

With the default port and a configured provider:

```bash
curl --fail --silent --show-error http://localhost:8000/api/extract \
  -F 'pdf_file=@sample_pdfs/meeting_minutes.pdf;type=application/pdf' \
  -F 'names=[{"first_name":"Thomas","last_name":"Muller"}]'

curl --fail --silent --show-error http://localhost:8000/api/ingest \
  -F 'pdf_file=@sample_pdfs/meeting_minutes.pdf;type=application/pdf'

# This sends the question and retrieved excerpts to the configured provider.
curl --fail --silent --show-error http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Who chaired the meeting?"}'
```

Extraction boxes use **zero-based** pages and PDF points; RAG source labels use
**one-based** physical pages. Literal citation checks do not prove semantic
support. See [the 25-question evaluation](docs/EVALUACION_FUENTES_RAG.md),
[test evidence](docs/TEST_LOG.md) and [manual review](docs/MANUAL_TEST_LOG.md).
`make smoke-extract` and `make smoke-rag` use isolated resources; the latter uses
a **simulated** generator and does not measure answer quality. `make test` runs
the local suite and requires the native prerequisites below.

For an isolated end-to-end check using real Gemini, configure a private `.env`
as above and run `make test-rag-real`. It sends synthetic test data to Google,
can consume quota or incur charges, and requires reviewing the returned answer.
The check uses real OCR, embeddings, Qdrant and generation; it does not establish
general accuracy. It does not change existing Compose services or volumes.

For repeated full names that the English NER model detected at least once,
`NER_NAME_RECOVERY_PASSES=1` in `.env` enables exact recovery on the existing OCR
text. The supplied `.env.example` uses `1`; the backend fallback without that
setting is `0` (off). Recovery can also add false
positives and cannot recover a name NER never detected. Review boxes and names;
the sample observations and limitations are in [test evidence](docs/TEST_LOG.md).

### React frontend

The `frontend` Compose service is included when you start the project with
`make up`, `make quickstart` or `docker compose up --build -d`. Open
**http://127.0.0.1:3000**, select a PDF and choose **Analizar PDF**. The optional
names field accepts JSON such as `[{"first_name":"Ana","last_name":"López"}]`.
Navigate pages or select a detected
name; boxes and fuzzy matches are taken directly from `/api/extract`. This basic
flow does **not** need a Gemini key or preview token. Recovery follows the same
backend setting as the API; `.env.example` enables level 1.

`FRONTEND_PORT` changes the host port; the frontend binds only to `127.0.0.1`.
It runs in a separate Nginx container and proxies `/api/` to the `app` container;
PDF.js renders the selected PDF in the browser. Nginx limits request bodies to
21 MiB; if backend upload limits are increased, configure Nginx accordingly.
Starting or rebuilding Compose may recreate **existing services**: do so only
when you intend to update that Compose project. The API itself has no user
authentication and must not be exposed to untrusted users. Browser memory,
caches and downloaded copies are not securely erased.

After extraction, OCR, NER and any enabled recovery stages load automatically;
there is no token field. Compose creates a private internal credential shared
between the app and frontend. The frontend verifies that the stored PDF and final
response match before offering overlays. Preview limits and expiry are described
below; if unavailable, the final result still works. An existing `.env` with
`EXTRACT_PREVIEW_ENABLED=false` keeps previews disabled until explicitly changed.

## Why this exists (the problem)

Let's imagine a company that processes large volumes of scanned documents (contracts, KYC forms,
filings) that mention people. For **compliance**, it isn't enough to know *that*
a name appears — a reviewer has to be able to **find it on the page** and
**double-check that specific name against other records** (an ID, a sanctions
list, an internal system). A name with no location is not auditable.

So the core requirement is: **given a PDF, return each person's name together
with exactly where it sits on the page** (page number + bounding box). That
location is what lets a human or a downstream system verify the match against
other information. The fuzzy-matching and RAG pieces build on the same extracted
content. Keep this "locate it so it can be verified" purpose in mind — it's why
bounding-box accuracy and correct pages matter more than they might first seem.

---

## What you're building

A FastAPI service exposing four endpoints. The request/response **contract is
fixed** by `app/models/schemas.py` — do not change those shapes (add fields only
if you have a reason and document it).

### 1. `GET /health`
Liveness probe. Returns `{"status": "ok"}` (plus anything else useful).

### 2. `POST /api/extract`  — names + bounding boxes + fuzzy match
`multipart/form-data`:
- `pdf_file`: a (scanned) PDF.
- `names`: a JSON string — a list of `{"first_name": ..., "last_name": ...}`.

Pipeline:
1. **OCR** the PDF (it is scanned — there is no selectable text layer).
2. **NER**: extract **person** names only (no organizations, places, dates).
3. **Bounding boxes**: locate each extracted name in the page and return its box
   in **PDF coordinate space** (points, 72 per inch — *not* raw image pixels),
   with a **0-based page number**.
4. **Fuzzy match** the extracted names against the provided `names`.

Response: `ExtractionResponse` (see `schemas.py`) — `extracted_names[]` with a
`bounding_box`, and `fuzzy_matches[]`.

### 3. `POST /api/ingest` — index a document for RAG
`multipart/form-data` with `pdf_file`. OCR → chunk → embed → store in a vector
database. Response: `IngestResponse` (`status`, `chunks_stored`).

### 4. `POST /api/ask` — answer a question with RAG
JSON `{"question": "..."}`. Embed the question, retrieve the most relevant
chunks, call an LLM to answer **grounded in the retrieved context**, and return
`RAGResponse` (`answer`, `sources`).

---

## Requirements that matter (this is the actual evaluation)

> **Scope & time.** This is time-boxed — we do **not** expect fully isolated
> infrastructure. An **embedded / in-process vector store (e.g. Chroma) running
> locally is completely fine**, and you do not need Docker to pass. Things like a
> `docker-compose.yml` with an isolated vector DB, a hardened container, or a
> clean separation of services are **not required** — but if you add them, they
> count as **positive extras** in the evaluation. Prioritize a correct,
> well-structured core; reach for the infra polish only if you have time.

Anyone can wire libraries together. We're hiring an **ML Engineer**, so we look
for production judgment:

- **Architecture** — SOLID, dependency injection, separation of concerns.
  Services depend on abstractions (Protocols/ABCs), not concrete singletons.
  HTTP routers stay thin; business logic is testable without HTTP.
- **Configuration** — no hardcoded hosts/ports/model names/thresholds/DPI.
  Centralized, environment-overridable config.
- **Resilience** — timeouts and retries on external calls (LLM, vector store);
  meaningful failure modes; no silent `except: pass`.
- **Validation** — reject non-PDFs (by content, not just extension), empty
  files, oversized uploads; validate request bodies.
- **Resource management** — no leaked file handles or temp files.
- **Observability** — structured logging with useful context.
- **Correctness details we will check**, e.g.:
  - OCR must process **every** page (including the first).
  - Bounding boxes must be in **PDF space**, not image pixels.
  - Name matching must be **case-insensitive** and robust to OCR noise and
    accents (`María González` ~ `Maria Gonzalez`); prefer full-string
    similarity over substring tricks.
  - RAG chunking must not cut words in half; retrieval must be grounded (no
    hallucinated `sources`).
  - Vector-store IDs must be unique across documents (a second ingest must not
    overwrite the first).
- **Tests** — you write them. Cover the tricky logic above with unit tests
  (mock the heavy models / external services) and at least one end-to-end path.
  We look at *what* you chose to test and how.
- **Containerization (bonus, not required)** — if you have time, a `Dockerfile`
  and a `docker-compose.yml` that brings up the app **and its dependencies** with
  `docker compose up` (and `GET /health` passing) is a strong positive. Skipping
  it costs you nothing on the core; a local/embedded setup is fine.
- **Audit viewer (bonus, not required)** — a simple frontend that, given a PDF,
  **renders the pages and draws the returned bounding boxes over the detected
  names**. This is the compliance reviewer's tool: it's how a human confirms a
  name really is where the API says it is. Nothing fancy — a single self-
  contained page (e.g. vanilla JS + pdf.js) that calls `/api/extract` and
  overlays the boxes is plenty. Strong positive if included.
- **DESIGN.md** (≤ 3 pages) — component + sequence view, technology choices and
  trade-offs, how you'd scale to 1000+ PDFs/hour, failure modes and mitigations,
  and — if you were to route between models by query complexity — how.

---

## Suggested stack (substitute freely, but justify it in DESIGN.md)

- Python 3.12, FastAPI, `pytest`
- OCR: Tesseract via `pytesseract` + `PyMuPDF` (PDF → image)
- NER: spaCy (`en_core_web_sm`); handle non-English if you add it
- Fuzzy: `thefuzz`
- Embeddings: `sentence-transformers`
- Vector DB: **Chroma** (embedded/local — simplest) or Qdrant if you prefer a
  separate service
- LLM: any OpenAI-compatible endpoint (configurable base URL + key)

Dependencies live in `pyproject.toml` and are managed with **[uv](https://docs.astral.sh/uv/)** — change them as you see fit (`uv add ...`). Commit the resulting `uv.lock`.

---

## Deliverables

1. A **branch + pull request** against this repo with your implementation.
2. `DESIGN.md`.
3. A short **`DECISIONS.md`** — notable engineering decisions and trade-offs
   (bullets are fine). This is where your reasoning earns credit.
4. Tests (required). `Dockerfile` / `docker-compose.yml` are **optional bonus**.

## How we evaluate (weights)

| Criterion | Weight |
|---|---|
| Correctness — the pipeline works on the sample PDFs | 30% |
| Architecture & design (SOLID, DI, abstractions, thin routers) | 20% |
| Engineering practices (config, logging, resilience, validation) | 20% |
| Code quality & decisions | 15% |
| Tests you wrote (coverage of the tricky logic) | 10% |
| Design document | 5% |

**Positive extras (bonus, on top of the above):** an **audit viewer** that
overlays the bounding boxes on the PDF, containerization (`Dockerfile` /
`docker-compose.yml`), a truly isolated vector DB, multi-language support,
batching, or other production hardening. Not required — credited when present.

## Local application development (outside Docker)

The application requires POSIX, Python 3.12, `uv`, Tesseract with English data,
and Qdrant 1.13.6. For example, install Tesseract with `brew install tesseract`
on macOS or `apt install tesseract-ocr tesseract-ocr-eng` on Debian. Install `uv`
from its [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
The locked spaCy model is installed by `uv sync`; provisioning the pinned
embedding model below requires network access. Runtime inference is local.

For a **new development environment** with a free local port, for example:

```bash
uv sync --locked --extra dev
# Starts a separate Qdrant with its own persistent named volume.
docker run -d --name document-intelligence-local-qdrant \
  -p 127.0.0.1:6333:6333 \
  -v document-intelligence-local-qdrant:/qdrant/storage qdrant/qdrant:v1.13.6

# Use a new private directory, not an existing ledger or collection from another deployment.
install -d -m 700 data/ingestion data/models
export QDRANT_URL=http://127.0.0.1:6333
export EMBEDDING_MODEL_DIR="$PWD/data/models/all-minilm-l6-v2"
export INGESTION_LEDGER_PATH="$PWD/data/ingestion/ledger.sqlite3"
uv run python app/core/embedding_model.py "$EMBEDDING_MODEL_DIR"

# First run make setup, or create .env as described in the quick start.
# Exported host paths above override their Compose values in .env.
uv run --env-file .env uvicorn app.main:app --reload
```

Python `Settings` does **not** automatically load `.env`; `uv run --env-file`
does. An existing container, port, directory or volume must be inspected before
reuse. Back up the Qdrant volume and ledger together; this local setup does not
support multiple hosts or an unrelated writer sharing the collection. For
`make test`, use the same local prerequisites and environment. Sample scanned
PDFs are in `sample_pdfs/`.

## Use of AI tools

Using AI assistants (Copilot, Claude, ChatGPT, agents) is **allowed and
expected** — that's how modern engineering works. Two conditions:

1. **Disclose it** in `DECISIONS.md` (what you used it for).
2. **Own every line.** In a follow-up conversation we will ask you to explain
   design choices, walk through your code, and make a live change. Code you
   can't reason about will not count in your favor.

We are evaluating *your* engineering judgment, not an agent's output. Submitting
something you don't understand is the one thing that fails this test.

---

## Docker development

The initial infrastructure runs FastAPI and Qdrant as separate containers. Docker
Engine and Docker Compose are required. Qdrant data persists in the `qdrant_data`
volume; it is not exposed directly to the host. The first build downloads the
Python dependencies and requires network access.

The Linux image installs the CPU-only PyTorch build; it does not require NVIDIA
drivers or CUDA. Changing to GPU acceleration requires a different build setup.

```bash
# Optional: create a private configuration without overwriting an existing one.
make setup
docker compose up --build
```

In another terminal:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

`GET /health` is a liveness check for the API, not a Qdrant readiness check.
`POST /api/extract`, `/api/ingest` and `/api/ask` are implemented. Answer
generation is disabled by default: valid questions return `503` until a provider
is explicitly configured. Provider protocol tests use simulated responses; a
separate synthetic evaluation used real Gemini. Recreate services only when
you intend to upgrade: an already running container does not pick up these changes.

### Configuring question answering

`POST /api/ask` accepts JSON `{"question":"..."}` and returns `answer` and
`sources`. Only completed, compatible ingestions are eligible. If no context is
found, it returns an abstention without calling the model. The model must return
an internal literal quote for every citation: it must be a nonempty exact
substring of the selected fragment and at most 512 characters. Any invalid
quote or ID rejects the complete answer with `503`, without a generation retry.
Exact quote validation prevents invented quotations but does not prove that the
quote logically supports the answer; it may also reject legitimate answers if
the model changes OCR spelling or whitespace.
The service does **not** provide multi-user access control: anyone permitted to
query it can receive information from any document in the shared collection.

Configure a single provider in a private environment file; use `.env.example`
for the full settings. The default `LLM_PROVIDER=disabled` sends no data:

```dotenv
LLM_PROVIDER=gemini   # or openai
LLM_MODEL=gemini-3.5-flash-lite
LLM_API_KEY=your-private-key
LLM_ALLOW_EXTERNAL=true
# OpenAI-compatible HTTPS base URL; used only when LLM_PROVIDER=openai.
LLM_OPENAI_BASE_URL=https://api.openai.com/v1
```

Model names and provider-specific capabilities must be checked independently.
Providers receive the question and retrieved excerpts; `LLM_ALLOW_EXTERNAL=true` is required in
addition to the provider, model and key. They may charge and apply their own data
policies; a Gemini free tier, if offered, is subject to current limits. Never
commit credentials. Privileged host users can inspect environment variables.
For OpenAI-compatible services the API key is sent to `LLM_OPENAI_BASE_URL`:
configure **only a trusted HTTPS destination**. Credentials in the URL, query
strings, fragments, redirects and insecure HTTP are rejected. The application
appends `/chat/completions` to the base URL. Changing the destination can send
both the key and document excerpts to the operator of that service.

The adapters use bounded HTTP responses and configurable deadlines. They do not
silently switch providers. `LLM_MAX_RETRIES` defaults to 1 and is limited to 0–3;
`LLM_RETRY_BACKOFF_SECONDS` defaults to 0.25 with exponential backoff. Only
connection failures and HTTP 500/502/503/504 are retried. A failed HTTP request
may already have consumed quota or incurred charges; set `LLM_MAX_RETRIES=0`
to disable retries. A 429, read/write timeout, invalid answer or citation is not
automatically retried. Unsupported models,
invalid model JSON or citations, unavailable dependencies and timeouts produce
errors rather than invented answers. Prompts treat document text as untrusted,
but this cannot guarantee resistance to prompt injection. Provider tests use
mock HTTP; real model availability, model compatibility, answer quality and
cost have not been established by those tests.

If the model provider returns a rate or quota limit, `/api/ask` returns `429`
without retrying. Other provider failures return `503`, and
timeouts return `504`. Safe error details distinguish provider configuration,
availability and invalid evidence from vector-store compatibility, request and
timeout errors. No credential, provider body, question or document text is
included in error messages. An unsuccessful request does not disable `/health`
or prevent a subsequent request; it does not silently return an invented answer.
After an uncertain ingestion write, follow the scoped cleanup procedure rather
than assuming the write failed.

To exercise real HTTP, OCR, embeddings, Qdrant and SQLite with a **test-only
simulated generator**, without affecting existing Compose resources:

```bash
SMOKE_IMAGE=document-intelligence-stage-preview:local bash scripts/smoke/rag_e2e.sh
```

The script creates an image-only synthetic PDF with an empty first page, calls
`/api/ingest` and `/api/ask`, checks input validation and the second-page source,
and removes its own containers and network on exit. No LLM API is called. The
answer is simulated and must not be treated as evidence of answer quality.
The Docker image must already exist; if necessary build it separately:

```bash
docker build -t document-intelligence-stage-preview:local .
```

To opt in to **one real Gemini question**, first configure a private `.env` and
then run `bash scripts/smoke/rag_e2e.sh --gemini`. This sends only synthetic data
to Google, may consume quota or incur charges, and prints the synthetic answer
for human review. The `.env` is not printed but its variables may be inspected
by privileged Docker users. The temporary bridge permits external network access
and is not a domain-level firewall. Neither mode publishes host ports or touches
existing Compose services. Both mount the current local `app/` read-only over the
image; neither is a packaged-image verification. Never deploy the test-only
`scripts/smoke/serve_ask_fake.py` server.

The OCR component returns words with page-relative character offsets and boxes
in PDF points, relative to the top-left of the **unrotated crop box**. It first
uses the visible orientation and tries an alternative when confidence is low;
this heuristic is not guaranteed to choose correctly and does not handle
arbitrary skew. Byte, page and rendered-pixel limits, DPI, language and timeouts
are configurable in `.env.example`. The image includes only English Tesseract
language data; other languages require their corresponding packages.

For asynchronous callers, `OCRService.extract_async(pdf_bytes)`,
`extract_file_async(path)` and `extract_stream_async(stream)` use supervised
POSIX worker processes. FastAPI creates one shared service during startup; the
dependency `app.api.dependencies.get_ocr_service` retrieves it. Concurrent jobs,
queued jobs, queue wait, upload, document and shutdown timeouts are configurable
per application process. A started job remains supervised after caller
cancellation; shutdown terminates its process group after the configured grace
period. This is not a durable queue and cannot guarantee cleanup after a machine
or container is killed abruptly.

### Extraction API

Send one PDF and a JSON array of name pairs as multipart form data. An empty list is valid.

```bash
curl --fail --silent --show-error http://localhost:8000/api/extract \
  -F 'pdf_file=@sample_pdfs/meeting_minutes.pdf;type=application/pdf' \
  -F 'names=[{"first_name":"Thomas","last_name":"Muller"}]'
```

The response follows `ExtractionResponse`: one `extracted_names` entry per
located occurrence and distinct `fuzzy_matches` pairs. Pages start at zero;
boxes use points relative to the top-left of the unrotated crop box. OCR is run
once per request. NER spans are mapped to OCR words on the same page; unsafe or
distant associations are omitted rather than assigned invented coordinates.
For a name split over adjacent lines, one enclosing rectangle may include blank
space. Full-name similarity ignores case and accents, removes apostrophes and
treats other punctuation as spaces. It uses `thefuzz.ratio` and returns scores
from 0 to 1; qualifying pairs retain deterministic input order.

`400`: invalid PDF or malformed `Content-Length`; `408`: upload timeout;
`413`: configured size or complexity limit; `422`: invalid multipart or names;
`503`: no capacity or dependency unavailable; `504`: processing timeout. Error
messages do not include document text.

| Variable | Default | Scope |
|---|---:|---|
| `MAX_REQUEST_BYTES` | 22020096 (21 MiB) | Entire extraction request body, including multipart boundaries, part headers, fields, and file. |
| `MAX_UPLOAD_BYTES` | 20971520 (20 MiB) | PDF limit enforced by OCR, separate from the request body. |
| `MAX_NAMES_BYTES` | 65536 (64 KiB) | Raw text-part size and UTF-8 size of the decoded JSON field. |
| `MAX_NAMES_COUNT` | 1000 | Maximum number of pairs; an empty list is valid. |
| `MAX_NAME_CHARS` | 512 | Maximum characters per query component and detected span. |
| `FUZZY_THRESHOLD` | 0.90 | Full-name matching threshold, finite and within `0..1`. |
| `EXTRACT_MAX_IN_FLIGHT` | 2 | Maximum in-flight extraction requests per application process. |
| `EXTRACT_UPLOAD_TIMEOUT_SECONDS` | 30 | Total body-read deadline. |
| `MAX_EXTRACTED_NAMES` | 1000 | Maximum original NER occurrences plus recovered occurrences. |
| `MAX_FUZZY_COMPARISONS` | 100000 | Maximum possible distinct extracted-name/query comparisons. |
| `MAX_FUZZY_WORK_UNITS` | 100000000 | Maximum product of total normalized extracted-name and query lengths. |

The body guard counts the actual ASGI chunks consumed by the application even
when `Content-Length` is missing or too small. It returns `413` when that limit
is exceeded, and `400` for malformed or repeated `Content-Length` headers. It
does not consume a body that the application never reads, and a response already
started cannot be changed to `413`. The endpoint consumes its form before
responding. A per-process admission limit is acquired before multipart parsing;
excess requests are rejected without reading their body. Uploads have a deadline,
and the multipart parser limits the PDF and text fields incrementally. These
controls are **not global** across HTTP workers or replicas. If a caller cancels,
already-started OCR/NER work remains supervised under its own service limits.

#### Optional recovery of repeated names

The backend fallback for `NER_NAME_RECOVERY_PASSES` is **0**: recovery is bypassed
and the existing response and order remain unchanged. The supplied `.env.example`
sets it to **1**; existing `.env` files keep their own setting. The allowed integer
levels are:

| Level | Additional searches over the existing page-local OCR words |
|---|---|
| `0` | Disabled; no candidate search. |
| `1` | Exact normalized names, ignoring case, accents and punctuation as in existing name normalization. |
| `2` | Level 1 plus component-by-component fuzzy comparison: same component count and order; each changed component scores at least 0.80 and differs by at most one insertion, deletion or substitution. At most two components may differ; components of three or fewer characters match exactly. |
| `3` | Levels 1 and 2 plus exact normalized text with spaces removed, for limited OCR word splitting/merging. The compact string must contain at least eight characters. |

Only names already detected by NER **and safely located** are references; they
must have 2–8 normalized components and no more than 512 source characters
(or the lower `MAX_NAME_CHARS`). References are fixed before the search,
so recovered candidates cannot recursively become references. Names never
detected by NER, text absent from OCR and unsafe bounding boxes cannot be
recovered. Search stays within each physical page and uses only its existing OCR
word boxes; OCR and spaCy are not rerun. Candidates matching multiple distinct
references or overlapping alternative candidates are conservatively omitted.
Existing NER locations are protected. Standalone bullets or punctuation at the
edges of a candidate are excluded, so they cannot create duplicate ambiguous
windows for the same name. Recovered text is the OCR spelling, not a
silently corrected name. With recovery enabled, output is ordered by page and
page-local offsets; the public response schema is unchanged.

The separate recovery component threshold is fixed at `0.80` and does not
change `FUZZY_THRESHOLD`, which still controls matching against requested names.
These rules can improve recall but can also produce false positives, including
different people with identical normalized names; no accuracy guarantee is
claimed. The API does not identify which individual locations were recovered.
Application logs contain only aggregate counts, not names.

Recovery has fixed per-document limits of 100,000 examined OCR windows,
100,000 comparisons and 100,000,000 normalization/comparison work units across enabled passes.
Over-budget requests return `413`, not partial results. One-word and long
multi-component NER names remain valid original detections, but are not used as
recovery references. Resource limits are per process and require calibration.

For a real, isolated HTTP/OCR/NER comparison of all four levels and temporary PDF
overlays for human review, build the current image and run:

```bash
docker build -t document-intelligence-name-recovery:local .
SMOKE_IMAGE=document-intelligence-name-recovery:local bash scripts/smoke/recuperacion_nombres.sh
```

The script pauses while the four annotated copies can be opened and compared;
press Enter or Ctrl-C to remove its own temporary files and containers. Use
`--automatico` for a no-pause check. It uses a sample PDF and real services;
unit tests use controlled NER omissions to test each rule deterministically.
This is not an accuracy evaluation or human approval MT-002. The currently
running Compose app does not pick up the new setting or code without a deliberate
upgrade/recreation; the script does not touch existing Compose resources.
The sample comparison and remaining evaluation limits are in
[docs/TEST_LOG.md](docs/TEST_LOG.md).

#### Optional authenticated preview

Compose enables this single-operator development feature by default and generates
its internal credential in a shared Docker volume. Set `EXTRACT_PREVIEW_ENABLED=false`
to disable it. An existing `.env` is never overwritten. Outside Compose, the
backend defaults to disabled; to opt in, configure a private, random
`EXTRACT_PREVIEW_TOKEN` of 32–256 printable non-space ASCII characters. For example, generate a token with
`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`; keep it out of
source control and logs. Environment variables can be inspected by privileged
operators or through Docker inspection.

When enabled, the service keeps **only the latest successful extraction** as an
in-memory proxy of the original PDF plus immutable stage overlays: OCR word
boxes, located NER spans, each enabled recovery pass and final results. The
React frontend can optionally draw these JSON boxes over the PDF rendered in the
browser. Coordinates are PDF points relative to the top-left of the
unrotated crop box, and physical page indices start at zero. `source` distinguishes
`ocr`, `ner`, and `recovery_1`–`recovery_3`.

Each valid multipart extraction invalidates the previous preview **before**
processing starts, even if the new extraction later fails; malformed forms
rejected earlier do not. A preview is published only after successful extraction,
and is invalidated after 10 minutes or process shutdown. An older concurrent
request cannot overwrite a newer preview. Old IDs return `404`; an already
delivered or copied document cannot be revoked, and Python memory is not securely
erased. No preview is stored in SQLite or a persistent volume. Existing upload
and OCR workers may still use their normal temporary files during processing.

The proxy is limited to 10 MiB, 25 pages, 5,000 OCR words, 2 MiB per stage and
8 MiB total stage data. A larger or unrepresentable preview is skipped without
failing extraction; the preview endpoint then returns `404`. Access requires
`Authorization: Bearer <token>` when accessing the backend directly. The local
frontend proxy supplies its internal credential automatically. Any local client
that can access the frontend can therefore access the latest preview too; this
is not user authentication. Do not expose that proxy to untrusted users:

```text
GET /api/extract/preview                         # ID and available stages
GET /api/extract/preview/{id}/document           # temporary PDF proxy
GET /api/extract/preview/{id}/stages/{stage}     # page-local JSON overlays
```

Responses use `Cache-Control: no-store`. The endpoints are deliberately omitted
from OpenAPI and do not change the fixed extraction response. This is a
**single trusted operator, single application process** development aid, not
multi-tenant authentication or a globally shared store. A token holder can see
the latest extraction from any client in that process. Multiple workers or
replicas do not share previews or a global “latest” guarantee. Do not expose the
service to untrusted clients or assume browser downloads or caches can be erased
remotely. The browser limits its page canvas to about 8 million pixels.

To check the protected API and see temporary annotated PDFs for OCR, NER,
recovery and final stages without changing existing Compose services:

```bash
docker build -t document-intelligence-stage-preview:local .
SMOKE_IMAGE=document-intelligence-stage-preview:local bash scripts/smoke/vista_etapas.sh
```

The script uses only its own container with `--network none`, a synthetic test
token and private temporary files. It verifies that a second extraction removes
access to the old ID; the files are removed on Enter or Ctrl-C. This is not a
replacement for human review or an evaluation of detection quality.

### Ingestion API

`POST /api/ingest` accepts exactly one `pdf_file` multipart part. It OCRs all
physical pages, prepares whole-word fragments, embeds them locally, and confirms
their storage in Qdrant before returning the fixed `IngestResponse`:

```bash
curl --fail --silent --show-error http://localhost:8000/api/ingest \
  -F 'pdf_file=@sample_pdfs/meeting_minutes.pdf;type=application/pdf'
# {"status":"success","chunks_stored":...}
```

The local `all-MiniLM-L6-v2` revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41` is provisioned during image build.
Only SHA-256-verified, allowlisted artifacts are copied to a private runtime
snapshot; extra files in a mounted model directory cannot alter the loader.
Inference uses CPU without downloading models. One lazy, supervised worker
reuses the model; preparation has a deadline and its private files are removed
after controlled termination. A machine/container crash cannot guarantee cleanup.

The initial fragment budget is **128 model tokens including special tokens**,
with **up to 32 overlapping content tokens**, adjusted to whole words. These are
a baseline, not a measured retrieval optimum. A single word that cannot fit or
produces no model tokens is rejected rather than silently truncated. The model's
`[UNK]` tokens are accepted: the original OCR text is retained in Qdrant, but
unknown characters or words can lose meaning in their embeddings. Empty OCR
pages produce no fragments but are recorded in SQLite with
their original zero-based physical page number; this is not proof a page was
visually blank. A document with no detected text returns `422` without points.

Every request has new document/ingestion UUIDs, even for identical PDF bytes.
The SHA-256 and processing signature in SQLite support future duplicate analysis;
automatic deduplication is not implemented. Qdrant retains fragment text and a
sanitized source filename, document/ingestion/chunk IDs, page and character
positions, model identity and processing signature. No original PDF is retained
permanently and document contents are not written to application logs. SQLite
stores operational metadata and all page statuses, not OCR text.

`INGEST_COLLECTION` is separate from the pre-existing `QDRANT_COLLECTION` setting.
It must use cosine distance and 384-dimensional vectors. Qdrant 1.13.6 does not
persist collection metadata, so a reserved manifest point binds the collection
to the model revision, endpoint and SQLite ledger identity. An existing unmarked
collection is **not adopted**, and incompatible/untagged data is refused, never
deleted automatically. Interrupted creation can leave an unmarked collection;
it must be inspected and resolved explicitly, not silently reused. The manifest
is not a document fragment: retrieval filters `kind=chunk` and excludes
incomplete ingestions using the ledger.

The `ingestion_data` Compose volume persists SQLite and same-host POSIX locks;
Qdrant persists in its separate `qdrant_data` volume. All application workers and
maintenance commands must share the same local ledger volume. Network filesystems,
multiple hosts, and independent writers bypassing these locks are not supported.
Back up/restore SQLite and Qdrant together; losing only the ledger can orphan data.
The ledger schema is versioned and incompatible files are refused without an
automatic migration. The earlier development-only schema v1 is not migrated.

| Variable | Default | Meaning |
|---|---:|---|
| `INGEST_COLLECTION` | `documents_minilm_1110a243_v1` | Dedicated owned collection, no automatic migration. |
| `INGEST_MAX_IN_FLIGHT` | 1 | Per-process admitted ingestions, no additional upload queue. |
| `INGEST_MAX_CHUNKS` | 1000 | Maximum for the **whole document**, not each page. |
| `INGEST_MAX_PAGE_CHARS` / `INGEST_MAX_DOCUMENT_CHARS` | 100000 / 1000000 | Original OCR preparation limits. |
| `INGEST_CHUNK_TOKENS` / `INGEST_OVERLAP_TOKENS` | 128 / 32 | Token budget and maximum overlap. |
| `INGEST_UPLOAD_TIMEOUT_SECONDS` | 30 | Upload deadline; existing PDF/body/page/pixel bounds also apply. |
| `INGEST_JOB_TIMEOUT_SECONDS` | 420 | Overall ingestion deadline, including OCR, embeddings and vector operations. |
| `EMBEDDING_BATCH_SIZE` | 16 | Local inference batch size. |
| `EMBEDDING_JOB_TIMEOUT_SECONDS` | 120 | Worker startup, chunking and inference deadline. |
| `EMBEDDING_QUERY_MAX_TOKENS` | 256 | Separate budget for queries, without silent truncation. |
| `QDRANT_TIMEOUT_SECONDS` / `QDRANT_READ_RETRIES` | 10 / 2 | Operation deadline and bounded read-only retries. Writes are not blindly retried. |
| `QDRANT_BATCH_SIZE` | 64 | Number of points per confirmed write. |

`400` invalid PDF; `408` upload timeout; `413` size/page/fragment limit; `422`
invalid form, no detected text or text that cannot be chunked; `503` dependency,
collection ownership or admission failure; `504` OCR/embedding deadline.
These are per-process bounds, not a production capacity guarantee. The embedding
worker serializes inference; increasing HTTP admission alone does not increase
embedding capacity. Deadlines trigger cancellation, but safe supervision and
local cleanup can make a response or shutdown take longer. The wrapper
`get_query_embedding()` is not an `/api/ask` API.

#### Recovery and scoped cleanup

SQLite and Qdrant do **not** share an atomic transaction. A failed attempt can
leave fragments in `cleanup_pending`; a process crash can leave `processing` or
`writing`. A timeout does not prove a remote write failed. Live operations hold
an OS lock per ingestion, and writes/cleanup also share a collection lock.
Maintenance never decides that a job is abandoned merely because it is old.

For an upgraded, already running Compose app (the script does not restart it):

```bash
# Inventory up to 100 IDs: no deletion or claim that attempts are inactive.
bash scripts/cleanup_ingest.sh --pending
# Preview one exact ingestion from the operational log/ledger.
bash scripts/cleanup_ingest.sh --id INGESTION_UUID
# Delete only that eligible failed ingestion, preserving completed documents.
bash scripts/cleanup_ingest.sh --id INGESTION_UUID --execute
```

An ambiguous write requires `--confirm-quiescent` **in addition** to `--execute`.
Only use it after stopping writers and draining/restarting the relevant Qdrant
instance so old writes cannot still arrive. A nonzero result means cleanup was
refused or remains unconfirmed. Preview does not change ledger states. Execution
can recover a dead local owner, verifies the collection/endpoint/model, deletes
only the ingestion's exact filter, and marks `cleaned` only after observing zero
matching points. It cannot protect against an unrelated writer bypassing locks
or a false operator confirmation. Do not schedule the confirmation flag blindly.
No automatic scheduler or Celery is configured.

Outside Compose, run `python -m app.maintenance.cleanup_ingest` with the same
configuration, user and ledger directory. New directories/files require `0700`/
`0600`; existing unrelated, empty, insecure or incompatible files are refused,
not overwritten or chmodded. A private lock file is never unlinked during normal
operations. If first-time initialization itself is killed and leaves an empty
file, inspect it before explicitly choosing a new path or removing that file.

#### Isolated real ingestion verification

```bash
docker build -t document-intelligence-smoke:local .
SMOKE_PACKAGED_APP=1 bash scripts/smoke/ingestion.sh
```

This check uses real Uvicorn, OCR, local embeddings, SQLite and Qdrant 1.13.6 on
an **internal network with no host-published ports**, with new temporary volumes.
It checks two PDFs, repeated content, empty physical pages and scoped cleanup,
then recreates the test API/Qdrant to check persistence. The cleanup fixture is
an explicitly synthetic partial-write record with a deliberately delayed write
to real Qdrant, not a real server timeout. A client-side manifest failure is also
injected to verify that an unmarked collection is not adopted. The check
does not stop existing Compose containers or touch their data. It removes only
its own resources; abrupt runner/Docker termination can prevent cleanup.
`SMOKE_IMAGE` and `SMOKE_QDRANT_IMAGE` select already available local images.
`SMOKE_PACKAGED_APP=1` tests the code packaged in the image; by default the
current `app/` directory is mounted read-only for development.
This is not a general retrieval-quality evaluation or human review MT-002.

For an optional isolated interactive walkthrough with a temporary Qdrant
Dashboard, SQLite snapshot and sample queries, run
`bash scripts/smoke/recorrido_visual.sh` after building the smoke image. It
publishes only loopback ports and removes its own resources on normal exit.

### Person detection

`uv.lock` pins spaCy 3.8.18 and the official `en_core_web_sm` 3.8.0 wheel,
including its SHA-256. The wheel is downloaded from the official spaCy model
release during `uv sync` or image build; the build verifies it loads. Inference
requires no network or model download. `NER_MODEL` defaults to `en_core_web_sm`;
another model must already be installed and compatible. A missing model raises a
specific error instead of returning an empty result.

`NERService.detect_pages()` receives a list of page strings and returns a list of
`PersonSpan` lists in the same order, including empty pages. Offsets are Python
character positions local to each page, with an exclusive end; repeated
occurrences are kept. The async service executes spaCy in lazy, persistent POSIX
worker processes and reuses the model within each worker. The FastAPI lifespan
owns one service per application process. Synchronous callers may use
`SpacyPersonRecognizer` or `extract_names`; they must not run those blocking
functions directly on an async event loop.

| Variable | Default | Meaning |
|---|---:|---|
| `NER_MODEL` | `en_core_web_sm` | Installed model. |
| `NER_MAX_PAGE_CHARS` | 100000 | Characters per page, at most 1,000,000. |
| `NER_MAX_DOCUMENT_CHARS` | 1000000 | Total characters across pages. |
| `NER_MAX_CONCURRENT_JOBS` | 1 | Active NER workers per application process. |
| `NER_MAX_QUEUED_JOBS` | 1 | Additional queued jobs per application process. |
| `NER_QUEUE_TIMEOUT_SECONDS` | 10 | Maximum queue wait. |
| `NER_JOB_TIMEOUT_SECONDS` | 60 | Worker startup and inference deadline. |
| `NER_SHUTDOWN_TIMEOUT_SECONDS` | 10 | Grace period for active work and worker exit. |

The existing `MAX_PDF_PAGES` also bounds the number of pages sent to NER. Limits
are per process, not shared across HTTP workers or replicas. Extraction admission
also bounds the HTTP flow per process. On a timeout the worker is
terminated; a cancelled caller does not release an already-running job's capacity
until that work finishes or times out. Abrupt machine/container termination cannot
guarantee cleanup. The English small model predicts entity labels: filtering
`PERSON` does **not** guarantee all outputs are people or all people are found.
Sample OCR/NER observations and their limitations are in `docs/TEST_LOG.md`.

### Smoke checks without a UI

These optional checks use the current code, real Tesseract and spaCy, and the
repository's `sample_pdfs/meeting_minutes.pdf`; there are no mocks. They require
Docker Engine. Build a dedicated local image once, and rebuild it when the
Dockerfile or dependencies change. Building may require network access, but does
not start or restart the existing Compose services.

```bash
# From the repository root:
docker build -t document-intelligence-smoke:local .

# Run one check at a time, or both:
bash scripts/smoke/ejecutar.sh components
bash scripts/smoke/ejecutar.sh http
bash scripts/smoke/ejecutar.sh all
```

`components` checks OCR word offsets, NER spans, page bounds and fuzzy matching
directly. `http` sends real HTTP requests to Uvicorn in the temporary container:
it checks the sample PDF, an empty name list, invalid inputs and the center of a
box in an **in-memory synthetic**, cropped and rotated scan. The scripts return
nonzero on failure. They expect the known names in the sample; counts and model
predictions may vary across environments.

Each check uses disposable containers with `--network none`; code, scripts and
sample PDFs are mounted read-only. HTTP uses loopback inside the container and
publishes no host ports. Only the HTTP container created by the runner is stopped;
cleanup cannot be guaranteed after an abrupt termination. The container uses its
image's configuration, not the host's Compose `.env`. To use another compatible
local image, set `SMOKE_IMAGE`, for example:

```bash
SMOKE_IMAGE=another-local-image:tag bash scripts/smoke/ejecutar.sh all
```

The field-size check expects `MAX_NAMES_BYTES` at most 1 MiB and enough request
capacity for the sample PDF and that field; the image built above uses compatible
defaults. These checks do not test Compose, Qdrant, production traffic or general
model accuracy, and do not replace pytest or human visual review (MT-002).

Test commands, observed results and incident resolutions are recorded in
[`docs/TEST_LOG.md`](docs/TEST_LOG.md); human review results are recorded in
[`docs/MANUAL_TEST_LOG.md`](docs/MANUAL_TEST_LOG.md); engineering decisions are in
[`DECISIONS.md`](DECISIONS.md). OCR limitations and failure handling are summarized
in [`DESIGN.md`](DESIGN.md).
