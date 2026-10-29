# CLAUDE.md

FastAPI service (Python 3.12, uv) that OCRs scanned PDFs to extract person names with
their page + bounding box in PDF points, fuzzy-matches them against a requested list,
and answers questions over ingested documents with RAG (README.md §What you're
building). Hexagonal architecture (TRD ADR-001).

> `CONSTITUTION.md` is the authority on how code is written; this file describes the
> current conventions. System-level decisions and ADRs live in
> `docs/trds/document-intelligence-trd.md` (+ `docs/adrs/`). The README is the PRD.

## Naming conventions

- Modules/files `snake_case.py`; classes `PascalCase`; functions/variables
  `snake_case`; constants `UPPER_SNAKE` (CONSTITUTION §10).
- Ports are role nouns as `Protocol`s (`OcrEngine`, `PersonNameRecognizer`,
  `Embedder`, `VectorStore`, `Reranker`, `AnswerGenerator`, `PdfRasterizer`); adapters
  are `<Tech><Port>` (`TesseractOcrEngine`, `ChromaVectorStore`) (TRD §2).
- Use cases are verb phrases: `ExtractNames`, `IngestDocument`, `AnswerQuestion`
  (TRD §3).
- Errors are named by the violated rule (`UploadIsNotPdf`, `LlmUnavailable`), never
  generic (CONSTITUTION §10, §12).
- Code, identifiers, commits and docs in English.

## Core code patterns

- **Dependency rule:** `domain` ← `application` ← `infrastructure` / `api`. Domain and
  application never import `fastapi`, `pydantic`, or any vendor SDK (CONSTITUTION §1.2,
  §2.1; ADR-012).
- **Composition root:** adapters are built once in the FastAPI lifespan (`app/main.py`)
  and injected via constructor; no module-level singletons, no service locator.
- **Fixed contract:** `app/models/schemas.py` shapes are frozen by the PRD — add
  optional fields only with a reason recorded in `DECISIONS.md`.
- **Errors:** `DomainError` → 4xx, `InfrastructureError` → 5xx with `request_id`;
  vendor exceptions translated inside the adapter (CONSTITUTION §8).
- **Config:** every host/port/model/threshold/DPI/limit comes from the `Settings`
  object (env-overridable); none hardcoded (README §Requirements).
- **Logging:** structured JSON, `event` names, `request_id` per request; never log
  person names or document text (CONSTITUTION §9).
- **Sync CPU work:** endpoints that OCR/embed are plain `def` (threadpool), not
  `async def` (TRD §8).

## Build & validation commands

<!-- PENDING: these become real in phase P0 (TRD §14). Update once pyproject is configured. -->
```bash
uv sync --extra dev                  # install
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy app                      # type-check (strict)
uv run lint-imports                  # hexagonal dependency contracts
uv run pytest -m "not integration"   # fast suite (fakes)
uv run pytest                        # full suite (needs Tesseract installed)
uv run uvicorn app.main:app --reload # run locally → http://localhost:8000/viewer
docker compose up --build            # container (APP_PORT overrides 8000)
```

## Layout

```
app/
  main.py              # app factory + lifespan = composition root (only place adapters are built)
  models/schemas.py    # FIXED HTTP contract (Pydantic) — do not reshape
  api/                 # driving adapter: routers, upload validation, error→status map, DI providers
  application/         # ports.py (Protocols) + use cases (plain classes)
  domain/              # pure: dataclasses, alignment & geometry, matching, chunking, errors
  infrastructure/      # one adapter per port + Settings + logging setup
tests/
  unit/ (domain, application, api — fakes, no Tesseract needed)
  integration/ (real engines, @pytest.mark.integration)   e2e/   golden/   fakes/
```

## Where to look (no duplication — read the source section)

| When you are… | Read |
|---|---|
| Adding a port/adapter, wiring DI | CONSTITUTION §1, §2.1, §4 |
| Touching OCR, NER, boxes, coordinates | TRD §2 (Extract flow), ADR-002, ADR-003, ADR-004 |
| Touching fuzzy matching | TRD ADR-005 |
| Touching ingest/ask | TRD ADR-006…ADR-011 |
| Writing tests or evals | CONSTITUTION §7, TRD §1 (thresholds), §11 |
| Planning a ticket, reviewing, opening the PR | `docs/requirements-traceability.md` |

Graded extraction invariants (README §Correctness): every page OCR'd incl. page 0 ·
0-based pages · boxes in PDF points, top-left origin (`pt = px × 72 / DPI`, converted
once in the OCR adapter) · PERSON label only · one box per real occurrence ·
honorifics excluded.

## Hard rules

- Run the full validation gate (above) before every commit that goes into a PR.
- Tests first (TDD): the failing test precedes the code (CONSTITUTION §11).
- Never change field names/types in `app/models/schemas.py`.
- Never commit secrets; `.env` is git-ignored — document keys in `.env.example`.
- No new dependency without an ADR (CONSTITUTION §12).
- No `except: pass`, no bare `Exception` raises, no `Any`/`type: ignore` without a
  justification comment.
- Never put PII (names, document text) in logs or error messages.

## Miscellaneous / Gotchas

<!-- Running list — add entries as you discover things the agent repeatedly misunderstands -->
- Windows dev box: Tesseract 5.5.3 lives at `C:\Program Files\Tesseract-OCR` (`eng` +
  `osd` only). If it isn't on PATH, set `DOCINTEL_TESSERACT_CMD` in `.env`; integration
  tests skip with a clear reason when no binary is found.
- uv may pick Anaconda's Python 3.9 by default → spaCy's `blis` fails to build. Pin the
  interpreter (`.python-version` = 3.12 / `uv run --python 3.12`).
- spaCy models are installed as pinned wheel URLs in `pyproject.toml`, not via
  `python -m spacy download` (uv venvs ship without pip).
- OCR text contains curly apostrophes (`O’Brien`); the Windows console (cp1252)
  mangles them — set `PYTHONIOENCODING=utf-8` when printing. Same fix when piping
  `lint-imports` output (its spinner emoji crashes cp1252 with `UnicodeEncodeError`).
- The repo lives under a OneDrive path with spaces — quote paths in shell commands.
- NER default is `en_core_web_lg` (ADR-013): `sm` leaked `'Atlas'`/`Forbes` as PERSON on
  the OCR text. Re-run `scripts/eval_ner.py --model <name>` before changing it.
- RAG models (e5 embedder, mmarco reranker) download to the Hugging Face cache on first
  start (~0.6 GB); torch comes from the CPU-only wheel index (`[tool.uv.sources]` in
  `pyproject.toml`) — never add a plain `torch` source. `app.main` imports torch, so any
  test importing it pays ~15 s once.
- Chroma on Windows keeps its files locked until `client.close()`
  (`ChromaVectorStore.close()`, run by the lifespan via `Container.on_shutdown`); tests
  that open a store must close it. Collection names need ≥ 3 characters.
- openai 3.x is built on `httpx2` (not `httpx`): inject `httpx2.Client(transport=
  httpx2.MockTransport(...))` to fake the LLM. Without `DOCINTEL_LLM_API_KEY` the app
  starts, `/api/ask` answers 503 `llm_not_configured`, `scripts/eval_answers.py` skips.
- There is no rerank-score gate (CR-002): the LLM decides "not found". Don't add a
  score threshold back — answerable and unanswerable scores overlap on these models.
  After changing `DOCINTEL_RERANKER_MODEL`, re-run `scripts/eval_retrieval.py` and
  `scripts/eval_answers.py`.
- Deliberate deviation from guati-factory `/create-rules`: no `.claude/context/`
  modules — they only duplicated the TRD/CONSTITUTION and aren't auto-loaded; this
  file points to the source sections instead.
