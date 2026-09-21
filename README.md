# Document Intelligence Service

A production-oriented FastAPI service for extracting person names and locations from scanned PDFs, fuzzy-matching detected names against candidate lists, and answering questions over ingested documents using retrieval-augmented generation (RAG).

## Features

* OCR of every PDF page using PyMuPDF and Tesseract.
* PERSON entity extraction with spaCy.
* Bounding boxes returned in PDF-point coordinates.
* Accent- and case-insensitive fuzzy name matching.
* PDF ingestion, word-safe chunking, embeddings, and ChromaDB vector storage.
* Grounded RAG question answering with configurable LLM providers.
* Local development with Ollama/Llama 3.
* OpenAI-compatible LLM endpoint support through environment configuration.
* Structured application logging and controlled external-service failures.
* Browser-based extraction Audit Viewer.
* Docker and Docker Compose support.

## Architecture

The application uses thin FastAPI routers, application services, dependency injection, and isolated infrastructure components.

```text
Client
  │
  ▼
FastAPI
  │
  ├── /extract ──► OCR → NER → Bounding Boxes → Fuzzy Matching
  │
  ├── /ingest ──► OCR → Chunking → Embeddings → ChromaDB
  │
  └── /ask ─────► Retrieval → Grounded Prompt → LLM → Answer + Sources
```

See [`DESIGN.md`](DESIGN.md) for the detailed architecture, scaling strategy, failure modes, testing approach, and limitations.

See [`DECISIONS.md`](DECISIONS.md) for the main engineering decisions, trade-offs, bonus features, and AI tooling disclosure.

## Requirements

* Python 3.12
* [uv](https://docs.astral.sh/uv/)
* Tesseract OCR
* Ollama with the configured local LLM for local RAG execution

The project uses the dependencies pinned in `uv.lock`.

## Local Setup

Install the project dependencies:

```text
uv sync
```

Install the required spaCy model:

```text
uv run python -m spacy download en_core_web_sm
```

For local RAG execution, start Ollama and make the configured model available.

The default application configuration uses:

```text
LLM provider: ollama
LLM model: llama3
LLM base URL: http://localhost:11434
```

Configuration can be overridden through `APP_*` environment variables. For example, an evaluator can configure an OpenAI-compatible endpoint without modifying application code.

## Running the API

Start the FastAPI application with:

```text
uv run uvicorn app.main:app --reload
```

The service is available at:

```text
http://localhost:8000
```

Health check:

```text
GET /health
```

## API Endpoints

### `POST /api/extract`

Upload a scanned PDF and a JSON list of candidate names.

The endpoint performs OCR, PERSON NER, PDF-coordinate bounding-box generation, and fuzzy matching.

### `POST /api/ingest`

Upload a PDF for OCR, chunking, embedding, and vector-store ingestion.

### `POST /api/ask`

Submit a question against previously ingested documents.

The response contains a grounded answer and sources derived from retrieved document metadata.

### `GET /audit`

Open the browser-based Audit Viewer for visually inspecting extracted-name bounding boxes.

## Testing

Run the normal automated regression suite:

```text
uv run pytest
```

The test suite is organized into:

```text
tests/
├── unit/
├── integration/
└── e2e/
```

The normal regression run covers unit and integration tests. The real E2E workflow uses the local OCR, embedding, ChromaDB, and LLM components and can be executed separately when those dependencies are available.

## Docker

Build and start the application with Docker Compose:

```text
docker compose up --build
```

The container exposes port `8000`.

Health check:

```text
http://localhost:8000/health
```

Audit Viewer:

```text
http://localhost:8000/audit
```

ChromaDB persistence is provided through a named Docker volume.

## Project Structure

```text
app/
├── api/             # FastAPI routers
├── models/          # API schemas
├── services/        # Application and infrastructure services
├── static/          # Audit Viewer
├── config.py        # Centralized configuration
├── dependencies.py  # Dependency injection
└── main.py          # Application entry point

tests/
├── unit/
├── integration/
└── e2e/

DECISIONS.md
DESIGN.md
Dockerfile
docker-compose.yml
pyproject.toml
uv.lock
```

## Validation

The implementation has been validated with automated unit/integration tests, a real end-to-end workflow using the local OCR, embeddings, ChromaDB, and Llama 3 components, real sample PDFs, Docker, Docker Compose, and the browser-based Audit Viewer.

AI-assisted development was used throughout the take-home and is disclosed in [`DECISIONS.md`](DECISIONS.md).
