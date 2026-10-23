# Running the Document Intelligence Service

How to install, run and test this implementation. `README.md` is the assignment brief and is left unchanged; design and reasoning are in [`DESIGN.md`](DESIGN.md) and [`DECISIONS.md`](DECISIONS.md), the test map in [`tests/README.md`](tests/README.md).

| Endpoint | Purpose |
| --- | --- |
| `POST /api/extract` | Person names with page and bounding box (PDF points, top-left origin) + fuzzy matches |
| `POST /api/ingest` | OCR → chunk → embed → store a PDF for question answering |
| `POST /api/ask` | Grounded answer with `sources` (`file.pdf#page=N`), or "not found" |
| `GET /health` | Liveness: `{"status": "ok"}` |
| `GET /health/ready` | Readiness of OCR, vector store, models and LLM (503 if a critical one fails) |
| `GET /viewer` | Audit viewer: draws the returned boxes over the PDF |
| `GET /docs` | OpenAPI documentation |

## 1. Prerequisites

| Tool | Needed for | Install |
| --- | --- | --- |
| Python 3.12 and [uv](https://docs.astral.sh/uv/) | Everything | `pip install uv` (or the uv installer) |
| Tesseract 5 with English data | Extract, ingest | Windows: [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki), then add `C:\Program Files\Tesseract-OCR` to `PATH` (or set `OCR__TESSERACT_CMD`) · macOS: `brew install tesseract` · Debian/Ubuntu: `apt install tesseract-ocr` |
| [Ollama](https://ollama.com/download) with a model | `/api/ask` only | `ollama pull llama3.2:1b` |

## 2. Install

```bash
uv sync --extra dev
```

This installs everything, **including the spaCy model** `en_core_web_lg` (pinned in `uv.lock`). Do **not** run `python -m spacy download`: it needs pip, which uv environments do not include, and it is not needed.

Download the embedding model once (≈ 90 MB; the first start would otherwise spend a minute or two downloading it):

```bash
uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

Optional: `cp .env.example .env` and edit it; every setting has a working default (section 6).

## 3. Run

```bash
uv run uvicorn app.main:app            # http://127.0.0.1:8000
```

The first request is served once the models are loaded (≈ 25 s on a laptop, mostly importing torch). Then:

```bash
curl http://127.0.0.1:8000/health/ready

curl -F "pdf_file=@sample_pdfs/company_memo.pdf" \
     -F 'names=[{"first_name":"Maria","last_name":"Garcia"},{"first_name":"Robert","last_name":"Chen"}]' \
     http://127.0.0.1:8000/api/extract

curl -F "pdf_file=@sample_pdfs/company_memo.pdf" http://127.0.0.1:8000/api/ingest

curl -H "Content-Type: application/json" \
     -d '{"question":"Who was promoted to Vice President of Engineering?"}' \
     http://127.0.0.1:8000/api/ask
```

Open **http://127.0.0.1:8000/viewer**, choose a PDF, list names one per line ("First Last"), and press *Extract*: each detected name is outlined on the page (green when it matches a listed name; hover for the score).

Errors are JSON `{"detail": "...", "request_id": "..."}` with status 415 (not a PDF), 422 (empty/corrupt file, bad `names`, invalid body), 413 (too large) or 503 (OCR, vector store or LLM unavailable).

## 4. Run with Docker

```bash
docker compose up --build
```

Starts the app on port 8000 with Qdrant and Ollama on an internal network (not published), pulls `llama3.2:1b` once, and waits for each dependency's healthcheck. The image bakes in Tesseract and both models and runs offline as a non-root user. `APP_PORT=9000` changes the host port; `LLM_MODEL=llama3.2` a larger model. The first build downloads several GB of images and Python wheels.

## 5. Test

```bash
uv run pytest                          # everything this machine supports
uv run pytest -m "not integration"     # fakes only: no Tesseract, models or Ollama needed
uv run pytest -m integration -rs       # the real pipeline; -rs shows why anything skipped
uv run pytest --cov                    # branch coverage (fails under 90 %)
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

Integration tests skip cleanly when their dependency is missing: Tesseract (OCR and the 55-name golden test), the spaCy or embedding model, or an LLM at `LLM__BASE_URL` (the grounded-answer test). `tests/README.md` maps each requirement of the brief to its tests.

Reproducible measurements:

```bash
uv run python scripts/evaluate_extraction.py                 # precision/recall on the 55 labelled names
OCR__DPI=150 uv run python scripts/evaluate_extraction.py    # any setting can be compared this way
uv run python scripts/calibrate_similarity.py                # thresholds for "not found"
uv run python scripts/draw_boxes.py sample_pdfs/company_memo.pdf out --layer names   # overlay PNGs
```

## 6. Configuration

Environment variables (or `.env`); nested groups use `__`. All are listed in `.env.example`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOG_LEVEL`, `LOG_JSON` | `INFO`, `true` | Log level; JSON or console format |
| `OCR__DPI` | `300` | Render resolution (150 is twice as fast with the same accuracy on the samples) |
| `OCR__LANG`, `OCR__PSM` | `eng`, `3` | Tesseract language(s) and page segmentation mode |
| `OCR__TESSERACT_CMD` | unset | Path to `tesseract` when it is not on `PATH` |
| `OCR__PAGE_TIMEOUT_S` | `120` | Per-page OCR limit |
| `NER__MODEL` | `en_core_web_lg` | spaCy pipeline; `en_core_web_sm` is smaller and misses 2 of 55 |
| `NER__PERSON_LABELS` | `["PERSON","PER"]` | Entity labels counted as people |
| `MATCHING__THRESHOLD` | `0.90` | Minimum fuzzy-match score |
| `RAG__CHUNK_WORDS`, `RAG__OVERLAP_WORDS` | `150`, `30` | Chunk window, in whole words |
| `RAG__TOP_K` | `5` | Chunks retrieved per question |
| `RAG__MIN_SIMILARITY` | `0.33` | Best match needed to answer at all (below: "not found", no LLM call) |
| `RAG__CONTEXT_MIN_SIMILARITY` | `0.30` | Similarity needed for a chunk to enter the prompt |
| `RAG__EMBEDDING_MODEL`, `RAG__EMBEDDING_BATCH_SIZE` | `sentence-transformers/all-MiniLM-L6-v2`, `32` | Embedding model and batch size |
| `RAG__VECTOR_STORE`, `RAG__COLLECTION` | `chroma`, `documents` | `chroma` or `qdrant`; collection name |
| `RAG__CHROMA_PATH` | `./data/chroma` | Chroma storage |
| `RAG__QDRANT_URL` | unset | Qdrant server; unset = embedded Qdrant at `RAG__QDRANT_PATH` (`./data/qdrant`) |
| `RAG__QDRANT_API_KEY`, `RAG__QDRANT_TIMEOUT_S`, `RAG__QDRANT_MAX_RETRIES`, `RAG__QDRANT_BACKOFF_S` | unset, `10`, `2`, `0.2` | Qdrant auth, timeout, retries, backoff |
| `LLM__BASE_URL` | `http://127.0.0.1:11434/v1` | Any OpenAI-compatible endpoint (Ollama by default) |
| `LLM__API_KEY`, `LLM__MODEL` | `ollama`, `llama3.2:1b` | Credentials and model |
| `LLM__TIMEOUT_S`, `LLM__MAX_RETRIES`, `LLM__TEMPERATURE` | `30`, `2`, `0` | Request timeout, retries, sampling |
| `LLM__READINESS_TIMEOUT_S` | `2` | Timeout of the `/health/ready` LLM probe |
| `LIMITS__MAX_UPLOAD_BYTES`, `LIMITS__MAX_PAGES` | `20971520`, `50` | Upload limits (413 above them) |
| `LIMITS__REQUEST_OVERHEAD_BYTES` | `1048576` | Allowance for multipart framing above the upload limit |

## 7. Layout

```text
app/
  api/        thin routers, request parsing, error handlers, dependency providers
  services/   use cases: documents, ocr, names, extraction, chunking, ingestion, ask, health
  domain/     value objects, errors, Protocols, pure functions (geometry, name normalisation)
  adapters/   PyMuPDF, Tesseract, spaCy, thefuzz, sentence-transformers, Chroma, Qdrant, OpenAI client
  core/       settings, logging, middleware
  container.py  the only place adapters are chosen
  static/viewer.html
tests/        unit · e2e (HTTP with fakes) · integration (real libraries) · fakes.py · fixtures/
scripts/      evaluate_extraction · calibrate_similarity · draw_boxes
```

## 8. Troubleshooting

| Symptom | Fix |
| --- | --- |
| 503 "Tesseract is not installed or not on PATH" | Install Tesseract, or set `OCR__TESSERACT_CMD` to the binary |
| `/api/ask` returns 503 | Start Ollama and `ollama pull llama3.2:1b`; check `GET /health/ready` |
| First answer slow or 2 s extra per connection | Use `127.0.0.1`, not `localhost`, in `LLM__BASE_URL` (Ollama listens on IPv4 only) |
| `No module named pip` from `spacy download` | Not needed: `uv sync` already installed the model |
| Windows warning about symlinks from Hugging Face | Harmless; the model is cached as copies |
