# Running

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 and every dependency from `uv.lock`, including the spaCy model, so no `spacy download` step is needed.
- Tesseract 5 on `PATH` (`tesseract --version`). Linux: `apt install tesseract-ocr`. Windows: the UB Mannheim installer, then add its folder to `PATH`.
- For `/api/ask` only, an OpenAI-compatible LLM. The default is local [Ollama](https://ollama.com) with `ollama pull qwen2.5:7b-instruct`. For a hosted model, set `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`.

Settings are optional. Copy `.env.example` to `.env` to change any of them; defaults live in `app/config.py`.

## Start

```bash
uv sync --extra dev
uv run uvicorn app.main:app
```

Keep the default single worker: embedded Chroma does not support several processes (see DESIGN.md, section 4). The first request that uses a model loads it, which can take about a minute. The first ingest also downloads the embedding model from Hugging Face (about 90 MB).

## Try it

```bash
curl http://127.0.0.1:8000/health

curl -F pdf_file=@sample_pdfs/company_memo.pdf \
     -F 'names=[{"first_name": "Robert", "last_name": "Chen"}]' \
     http://127.0.0.1:8000/api/extract

curl -F pdf_file=@sample_pdfs/company_memo.pdf http://127.0.0.1:8000/api/ingest

curl -H "Content-Type: application/json" \
     -d '{"question": "Who was promoted to Vice President of Engineering?"}' \
     http://127.0.0.1:8000/api/ask
```

On Windows, run them in Git Bash, or in PowerShell 7.3+ with each command on one line (Windows PowerShell 5.1 strips the JSON quotes). Interactive docs are at `http://127.0.0.1:8000/docs`. Audit viewer: open `http://127.0.0.1:8000/viewer/`. To ingest PDFs and ask questions in the browser: `http://127.0.0.1:8000/viewer/ask.html`.

## Tests

```bash
uv run pytest tests/unit      # fakes only: no Tesseract, models, network or LLM
uv run pytest                 # adds integration tests (see below)
uv run ruff check . && uv run ruff format --check .
```

Tesseract tests skip without Tesseract. RAG tests skip until MiniLM is in the Hugging Face cache (after the first ingest) and, for answers, until Ollama serves the model. The spaCy model ships with `uv sync`.

CI (`.github/workflows/ci.yml`) runs ruff and `pytest` on every push and PR with Tesseract installed; the RAG tests skip there (no MiniLM cache, no Ollama).
