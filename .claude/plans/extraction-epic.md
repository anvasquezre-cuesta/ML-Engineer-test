# Feature: Extraction epic (T-001 … T-007)

The following plan should be complete, but it's important that you validate documentation
and codebase patterns and task sanity before you start implementing. Execute the tickets in
order; **each ticket ends with the full validation gate green and its own commit**. Stop and
report if a gate cannot be made green without changing an approved ticket or ADR.

## Feature Description

`POST /api/extract` for scanned PDFs: OCR every page → PERSON names via spaCy → one bounding
box per occurrence in PDF points (top-left origin) via char-offset alignment → fuzzy matches
against a requested name list. Built on a hexagonal walking skeleton (config, JSON logging,
error mapping, import-linter-enforced layers) and guarded by edge validation of uploads.

## User Story

As a compliance reviewer
I want to upload a scanned PDF with the names I'm checking and get every person mention with its page and exact box, plus matches against my list
So that I can verify each mention on the page and cross-check it against other records

## Problem Statement

The repo is a stub (`app/services/*.py` raise `NotImplementedError`). Nothing runs, nothing is
tested, and the graded invariants (all pages, PDF points, PERSON only, one box per
occurrence, accent/case/noise-robust full-string matching, content-based validation, no
leaks, structured logs) have no implementation.

## Solution Statement

Implement the 7 approved tickets in `docs/specs/extraction/` exactly as specified, under
`CONSTITUTION.md` and TRD ADR-001…ADR-007 + ADR-012. The shared contracts below are fixed
for the whole epic so tickets compose without rework.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: High (epic of 7 tickets)
**Primary Systems Affected**: whole `app/`, `tests/`, `scripts/`, `pyproject.toml`
**Dependencies**: fastapi, uvicorn, python-multipart, pydantic, pydantic-settings, pymupdf, pytesseract, pillow, spacy + en_core_web_sm wheel, rapidfuzz; dev: pytest, httpx, ruff, mypy, import-linter. System: Tesseract ≥ 5 (installed: 5.5.3, `eng` only).

---

## CONTEXT REFERENCES

### Files to read before implementing

- `README.md` — PRD; §What you're building (contract), §Requirements that matter (graded rules).
- `app/models/schemas.py` (whole file, 62 lines) — FIXED contract. `BoundingBox.page_number ≥ 0`, `FuzzyMatch.score ∈ [0,1]`, `NamePair` min_length=1. Never edit.
- `CONSTITUTION.md` §1.2 (dependency rule), §2.1 (FastAPI mapping table), §4 (ports, §4.5 DI), §6 (config), §7 (testing), §8 (errors, timeouts, edge validation, scoped resources), §9 (logging, PII), §10 (naming), §12 (negative list).
- `CLAUDE.md` — layout, naming, gotchas (Windows Tesseract path, Python 3.12 pin, spaCy wheel URL, curly apostrophes, `'Atlas'`).
- `docs/trds/document-intelligence-trd.md` §2 (flows), ADR-002…ADR-005, §11 (evals), §15 S1.
- `docs/specs/extraction/T-00N-*.md` — the acceptance criteria are the tests.
- `docs/requirements-traceability.md` — final checklist before the epic is declared done.
- Existing stubs to DELETE in T-001: `app/services/*.py` (8 files). `app/api/rag.py` stays as an empty router (RAG epic).

### Verified library facts (probed 2026-10-21 in a scratch venv)

| Library | Version | Facts that matter |
|---|---|---|
| pymupdf | 2.0 | `import pymupdf` (`fitz` emits FutureWarning — don't use). `pymupdf.open(stream=b, filetype="pdf")`; corrupt bytes raise `pymupdf.FileDataError` (subclass of `RuntimeError`); `doc.needs_pass`, `doc.is_encrypted`, `doc.page_count`; `page.rect` in points (612×792 for samples); `page.get_pixmap(dpi=N)` → `pix.width/height`, `pix.tobytes("png")`. Rotation-aware: `page.rect` is the displayed size. Encrypted test PDFs: `doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")`. |
| pytesseract | 0.3.13 | `image_to_data(image, lang=, config=, timeout=, output_type=pytesseract.Output.DICT)` → keys `text, conf, left, top, width, height, block_num, par_num, line_num, word_num`; `conf` is `-1` for non-word rows. `TesseractNotFoundError` ⊂ `OSError`; timeout raises `RuntimeError("Tesseract process timeout")`; `pytesseract.pytesseract.tesseract_cmd` sets the binary path. No type stubs. |
| fastapi | 0.157.0 | `TestClient` needs `httpx`. Lifespan via `FastAPI(lifespan=...)`. |
| pydantic-settings | 2.16.1 | `BaseSettings` + `SettingsConfigDict(env_prefix="DOCINTEL_", env_file=".env", extra="ignore")`. |
| rapidfuzz | 3.14.6 | `fuzz.ratio`, `fuzz.token_sort_ratio` return 0–100. |
| import-linter | 2.15 | `[tool.importlinter] root_package="app"`; contract types `layers`, `forbidden`, `independence`; `ignore_imports` list. |
| ruff 0.17.1 · mypy 2.4.0 · pytest 9.1.1 · pillow 13.0.0 · uvicorn 0.54.0 · python-multipart 0.0.32 | | |
| spacy | 3.8.x | Model wheel: `en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl`. Requires Python 3.12 (Anaconda 3.9 fails building `blis`). Preliminary run: honorifics excluded, `'Atlas'` → PERSON (false positive). |
| Tesseract | 5.5.3 | Installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`; languages: `eng`, `osd`. |

### Relevant Documentation

- PyMuPDF Document/Page/Pixmap — https://pymupdf.readthedocs.io/en/latest/document.html , /page.html#Page.get_pixmap — rendering + encryption flags.
- pytesseract — https://github.com/madmaze/pytesseract#functions — `image_to_data`.
- Tesseract page segmentation modes — https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html#page-segmentation-method — `--psm 3` default for full pages, `--psm 7` for single-line crops (box self-check).
- spaCy NER labels — https://spacy.io/models/en#en_core_web_sm-labels — `PERSON`.
- rapidfuzz fuzz — https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html — `ratio`, `token_sort_ratio`.
- import-linter contracts — https://import-linter.readthedocs.io/en/stable/contract_types.html — layers (incl. `|` independent siblings), forbidden.
- FastAPI lifespan / testing / dependency overrides — https://fastapi.tiangolo.com/advanced/events/ , /tutorial/testing/ , /advanced/testing-dependencies/.
- pydantic-settings — https://docs.pydantic.dev/latest/concepts/pydantic_settings/.

---

## SHARED CONTRACTS (fixed for the whole epic)

### Package layout

```
app/
  main.py                      # create_app(settings=None, build_container=build_container) + lifespan
  models/schemas.py            # untouched
  domain/
    errors.py                  # DomainError / InfrastructureError hierarchy (stable `code`)
    geometry.py                # BoundingBox, pixels_to_points, union_box
    document.py                # Word, Page, PageImage, PdfInfo
    names.py                   # HONORIFICS, strip_leading_honorific, normalize_name
    page_text.py               # PageText, build_page_text
    persons.py                 # PersonSpan, NameOccurrence
    alignment.py               # locate_occurrences
    name_matching.py           # RequestedName, NameMatch, match_names
  application/
    ports.py                   # PdfRasterizer, OcrEngine, PersonNameRecognizer (Protocols)
    extract_names.py           # ExtractNames, ExtractionResult
  infrastructure/
    settings.py                # Settings (pydantic-settings)
    logging.py                 # JsonFormatter, request_id contextvar, configure_logging
    pymupdf_rasterizer.py      # PyMuPdfRasterizer
    tesseract_ocr.py           # TesseractOcrEngine
    spacy_recognizer.py        # SpacyPersonNameRecognizer
  api/
    errors.py                  # STATUS_BY_CODE, exception handlers
    middleware.py              # RequestIdMiddleware
    health.py                  # GET /health
    dependencies.py            # Container dataclass + providers (read request.app.state.container)
    mapping.py                 # domain → schemas DTOs
    extract.py                 # POST /api/extract
    upload.py                  # read_pdf_upload (T-007)
    rag.py                     # existing empty router (untouched until RAG epic)
scripts/  eval_ner.py  eval_boxes.py
tests/
  conftest.py  fakes/  golden/persons.json  golden/name_pairs.json
  unit/domain/  unit/application/  unit/api/  integration/  e2e/
```

### Domain types (stdlib `@dataclass(frozen=True, slots=True)`; validate in `__post_init__`)

- `BoundingBox(x: float, y: float, width: float, height: float)` — PDF points, top-left origin, all ≥ 0 else `ValueError`.
- `pixels_to_points(x_px, y_px, w_px, h_px, dpi) -> BoundingBox` — `v * 72 / dpi`; `dpi ≤ 0` → `ValueError`. The ONLY px→pt conversion in the codebase.
- `union_box(boxes: Sequence[BoundingBox]) -> BoundingBox` — min x/y, max right/bottom; empty → `ValueError`.
- `Word(text: str, box: BoundingBox, confidence: float, line_key: tuple[int, int, int])` — `line_key = (block, paragraph, line)`.
- `Page(index: int, width: float, height: float, words: tuple[Word, ...])` — `index ≥ 0`.
- `PageImage(index: int, width_pt: float, height_pt: float, dpi: int, png: bytes)`.
- `PdfInfo(page_count: int, encrypted: bool)`.
- `PageText(text: str, word_spans: tuple[tuple[int, int], ...])` — `word_spans[i]` = `[start, end)` of `page.words[i]`.
- `PersonSpan(start: int, end: int, text: str)`.
- `NameOccurrence(name: str, page_index: int, box: BoundingBox)`.
- `RequestedName(first_name: str, last_name: str)` → property `full_name = f"{first} {last}"`.
- `NameMatch(extracted_name: str, matched_name: str, score: float)`.
- `ExtractionResult(page_count: int, occurrences: tuple[NameOccurrence, ...], matches: tuple[NameMatch, ...])` (application).

### Ports (`app/application/ports.py`, `typing.Protocol`, domain types only)

```python
class PdfRasterizer(Protocol):
    def probe(self, pdf: bytes) -> PdfInfo: ...                       # raises PdfUnreadable
    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]: ...  # every page, index 0..n-1; raises PdfUnreadable / PdfEncrypted
class OcrEngine(Protocol):
    def recognize(self, image: PageImage) -> Page: ...                # words in PDF points; raises OcrUnavailable
class PersonNameRecognizer(Protocol):
    def recognize(self, text: str) -> list[PersonSpan]: ...           # PERSON only, honorific-trimmed; raises NerModelUnavailable
```

### Errors (`app/domain/errors.py`) and HTTP mapping (`app/api/errors.py`)

`DomainError(message)` and `InfrastructureError(message)` each have a class attribute `code: str`.

| Class | Base | code | HTTP |
|---|---|---|---|
| `UploadMissing` | Domain | `pdf_file_missing` | 422 |
| `UploadEmpty` | Domain | `upload_empty` | 400 |
| `UploadTooLarge` | Domain | `upload_too_large` | 413 |
| `UploadIsNotPdf` | Domain | `upload_not_pdf` | 415 |
| `PdfEncrypted` | Domain | `pdf_encrypted` | 422 |
| `PdfUnreadable` | Domain | `pdf_unreadable` | 422 |
| `PdfTooManyPages` | Domain | `pdf_too_many_pages` | 413 |
| `NamesInvalid` | Domain | `names_invalid` | 422 |
| `OcrUnavailable` | Infrastructure | `ocr_unavailable` | 503 |
| `NerModelUnavailable` | Infrastructure | `ner_model_unavailable` | 503 |
| (FastAPI `RequestValidationError`) | — | `request_invalid` | 422 |
| (anything else) | — | `internal_error` | 500 |

Default for an unmapped `DomainError` = 422, `InfrastructureError` = 503. Body: `{"error": {"code", "message", "request_id"}}`. The HTTP table lives only in `app/api/errors.py` (domain knows no status codes).

### Settings (`app/infrastructure/settings.py`, prefix `DOCINTEL_`, `.env` supported)

| Field | Type / default | Constraint |
|---|---|---|
| `log_level` | `str = "INFO"` | one of DEBUG/INFO/WARNING/ERROR |
| `max_upload_bytes` | `int = 20 * 1024 * 1024` | > 0 |
| `max_pages` | `int = 50` | > 0 |
| `render_dpi` | `int = 300` | 72 ≤ v ≤ 600 |
| `ocr_languages` | `str = "eng"` | non-empty |
| `ocr_confidence_floor` | `float = 30.0` | 0 ≤ v ≤ 100 |
| `ocr_timeout_seconds` | `float = 60.0` | > 0 |
| `tesseract_cmd` | `str \| None = None` | None → `tesseract` on PATH |
| `ner_model` | `str = "en_core_web_sm"` | non-empty |
| `fuzzy_threshold` | `float = 0.90` | 0 ≤ v ≤ 1 |

Invalid value → `pydantic.ValidationError` whose message names the env key; `create_app()` fails fast.

### Logging contract

One JSON object per line: `timestamp` (UTC ISO-8601 `Z`), `level`, `event` (= the log message, snake_case name), `request_id` (from contextvar, `null` outside requests), `logger`, plus every key passed via `extra={...}`; `exc_info` → `"exception"` string. Usage everywhere: `logger.info("ocr_completed", extra={"page_count": n, ...})`. Never pass names or document text.

### Import-linter contracts (`pyproject.toml`)

```toml
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "Hexagonal layers"
type = "layers"
layers = ["app.main", "app.api | app.infrastructure", "app.application", "app.domain"]
ignore_imports = ["app.api.middleware -> app.infrastructure.logging"]   # request_id contextvar only

[[tool.importlinter.contracts]]
name = "Domain and application are framework-free"
type = "forbidden"
source_modules = ["app.domain", "app.application"]
forbidden_modules = ["fastapi", "starlette", "pydantic", "pydantic_settings", "pymupdf", "fitz", "pytesseract", "PIL", "spacy"]
```

`app.models` is not in any layer; add a forbidden contract that `app.domain` and `app.application` don't import `app.models`. If the `|` independent-layer syntax is rejected, replace with one `layers` contract per sibling plus an `independence` contract between `app.api` and `app.infrastructure` (same `ignore_imports`). `forbidden` on external modules needs `include_external_packages = true`.

### Composition root

```python
@dataclass(frozen=True)
class Container:            # app/api/dependencies.py — no Settings field (see amendment below)
    upload_limits: UploadLimits   # api-owned dataclass (max_bytes, max_pages), added in T-007
    rasterizer: PdfRasterizer
    extract_names: ExtractNames

def build_container(settings: Settings) -> Container   # app/main.py — the only place adapters are instantiated
def create_app(settings: Settings | None = None,
               build_container: Callable[[Settings], Container] = build_container) -> FastAPI
```

**Amendment (T-001 execution, 2026-10-21):** `Container` must not hold `Settings` —
`Settings` lives in `app.infrastructure`, and T-001 + the layers contract forbid `app.api`
importing `app.infrastructure`. The api layer owns the plain values it needs
(`UploadLimits` in `app/api/upload.py`, T-007); `build_container` copies them from
`Settings`. T-001's `Container` is therefore empty. Error handlers read the request id from
`request.state` (set by the middleware), so only `middleware -> logging` is ignored.
`create_app` loads settings via `load_settings()`, which re-raises `ValidationError` as
`ConfigurationInvalid` naming the `DOCINTEL_*` variable (T-001 alt flow).

Lifespan: `configure_logging(settings.log_level)` → `app.state.container = build_container(settings)`. Providers: `get_container(request) -> Container`, `get_extract_names(...)`. API tests pass a `build_container` returning fakes, so no model or binary is loaded. The spaCy model loads in `SpacyPersonNameRecognizer.__init__` (once, at startup); a missing model raises `NerModelUnavailable` at startup (fail fast, logged). Tesseract absence is detected per call (`OcrUnavailable` → 503), so `/health` still works without it.

---

## IMPLEMENTATION PLAN

### Phase 1: Foundation (T-001)
Project config + tooling, layout, settings, logging, errors, health, gate.

### Phase 2: Core domain + adapters (T-002, T-003, T-004, T-005)
Matching (pure), OCR adapters + geometry, recognizer + golden set + S1 eval, alignment (pure).

### Phase 3: Integration (T-006)
`ExtractNames` use case, router, mapping, wiring, e2e, box self-check eval.

### Phase 4: Hardening (T-007)
Edge validation of uploads and names.

---

## STEP-BY-STEP TASKS

TDD on every task: write the test, see it fail, implement, see it pass.

### ═══ T-001 Walking skeleton ═══

#### UPDATE `pyproject.toml`
- **IMPLEMENT**: `requires-python = ">=3.12,<3.13"`. Dependencies: `fastapi`, `uvicorn[standard]`, `python-multipart`, `pydantic>=2.14`, `pydantic-settings>=2.16`, `pymupdf>=2.0,<3`, `pytesseract>=0.3.13`, `pillow`, `spacy>=3.8,<3.9`, `en-core-web-sm @ <wheel URL>`, `rapidfuzz>=3.14`. **Remove** `thefuzz`, `python-Levenshtein` (ADR-005) and `sentence-transformers`, `chromadb`, `httpx` from runtime deps — RAG epic re-adds its libs (keeps `uv sync` from pulling torch now). Dev extra: `pytest>=9`, `httpx`, `ruff`, `mypy`, `import-linter`. Remove `pytest-asyncio` (no async tests). Add `[tool.hatch.metadata] allow-direct-references = true` (needed for the wheel URL).
- **ADD**: `[tool.ruff]` line-length 100, target py312; lint select `E,F,W,I,B,UP,S,BLE,N,SIM,RUF`; per-file-ignores `tests/**` and `scripts/**`: `S101`. `[tool.mypy]` `strict = true`, `files = ["app"]`; overrides `ignore_missing_imports = true` for `pytesseract`, `spacy.*`. `[tool.pytest.ini_options]` `testpaths=["tests"]`, `markers = ["integration: needs Tesseract/spaCy model", "eval: golden-set evaluations"]`, `addopts = "-ra --strict-markers"`. Import-linter contracts above.
- **CREATE**: `.python-version` → `3.12`.
- **GOTCHA**: `uv sync` must run with Python 3.12 (Anaconda 3.9 is first on PATH).
- **VALIDATE**: `uv sync --extra dev && uv run python -c "import pymupdf, pytesseract, spacy, rapidfuzz, fastapi; spacy.load('en_core_web_sm')"`

#### REMOVE `app/services/` (all 8 files)
- **VALIDATE**: `test ! -d app/services`

#### CREATE `app/domain/errors.py`, `app/infrastructure/settings.py`, `app/infrastructure/logging.py`
- **IMPLEMENT**: per shared contracts. All error classes for the epic are declared now (one place). `JsonFormatter.format` builds the dict from `record.__dict__` minus stdlib attributes. `request_id_var: ContextVar[str | None]`. `configure_logging(level)` sets a single stdout handler on the root logger (idempotent).
- **TESTS** `tests/unit/infrastructure/test_settings.py`: defaults load; `DOCINTEL_RENDER_DPI=200` via `monkeypatch.setenv` → 200; `DOCINTEL_FUZZY_THRESHOLD=1.7` → `ValidationError` mentioning `fuzzy_threshold`. `tests/unit/infrastructure/test_logging.py`: record with `extra` → valid JSON with `event`, `timestamp` ending `Z`, extras, `request_id` from contextvar.
- **VALIDATE**: `uv run pytest tests/unit/infrastructure -q`

#### CREATE `app/api/errors.py`, `app/api/middleware.py`, `app/api/health.py`, `app/api/dependencies.py`, UPDATE `app/main.py`
- **IMPLEMENT**: handlers for `DomainError`, `InfrastructureError`, `RequestValidationError`, `Exception` (500, `logger.exception("unhandled_error")`, generic message). `RequestIdMiddleware` (pure ASGI or `BaseHTTPMiddleware`): reuse `X-Request-ID` or `uuid4().hex`, set contextvar, echo header, log `request_completed` with `method`, `path`, `status`, `duration_ms`. Health router returns `HealthResponse(status="ok")` with `response_model=HealthResponse`. `create_app` per shared contract; include `rag_router` unchanged; module-level `app = create_app()` kept for `uvicorn app.main:app` (lifespan defers heavy work, so import stays cheap).
- **GOTCHA**: in T-001, `Container()` is empty; `rasterizer`/`extract_names` are added in T-006 and `upload_limits` in T-007 (rule: no speculative fields). See the composition-root amendment.
- **TESTS** `tests/unit/api/test_health.py`, `test_errors.py` (test-only routes raising a `DomainError` subclass, an `InfrastructureError` subclass, a `ValueError` → 4xx/503/500, body shape, no traceback text), `test_request_id.py` (header echo + `caplog` single `request_completed` record). Use `TestClient(create_app(build_container=fake_builder))` and `raise_server_exceptions=False` for the 500 case.
- **VALIDATE**: `uv run pytest tests/unit -q`

#### CREATE `.env.example`, UPDATE `CLAUDE.md`
- **IMPLEMENT**: every `Settings` key with its default and a one-line comment; Windows note for `DOCINTEL_TESSERACT_CMD`. In `CLAUDE.md` replace the PENDING marker with the real gate commands (below).
- **VALIDATE**: `uv run python -c "from app.infrastructure.settings import Settings; import re,sys; keys={f'DOCINTEL_{k.upper()}' for k in Settings.model_fields}; txt=open('.env.example').read(); missing=[k for k in keys if k not in txt]; sys.exit(1 if missing else print('ok'))"`

#### GATE + COMMIT
- Full gate (Level 1 + Level 2). Prove the linter bites: temporarily add `import fastapi` to `app/domain/errors.py`, confirm `lint-imports` exits non-zero, revert.
- `git commit -m "feat(T-001): walking skeleton with health, settings, JSON logging and quality gate"` (+ attribution lines).

### ═══ T-002 Name matching ═══

#### CREATE `app/domain/names.py`
- **IMPLEMENT**: `HONORIFICS = frozenset({"dr", "prof", "mr", "mrs", "ms"})`. `normalize_name(s)`: casefold → NFKD drop `unicodedata.combining` → replace every char that is not alphanumeric/space with a space (covers `'`, `’`, `-`, `,`, `.`) → split → drop leading tokens in `HONORIFICS` → join with single spaces. `strip_leading_honorific(span: PersonSpan) -> PersonSpan` (used by T-004): while the span text starts with an honorific token (with optional `.`) followed by whitespace, advance `start` and trim `text`.
- **TESTS** `tests/unit/domain/test_names.py`: `"MARÍA GONZÁLEZ"` → `"maria gonzalez"`; `"Dr. Kevin O’Brien"` → `"kevin o brien"`; `"Al-Rashidi"` → `"al rashidi"`; whitespace collapse; empty → `""`.

#### CREATE `app/domain/name_matching.py` + `tests/golden/name_pairs.json`
- **IMPLEMENT**: `match_names(extracted: Sequence[str], requested: Sequence[RequestedName], threshold: float) -> list[NameMatch]`: dedupe extracted (preserve first spelling), normalize both, score = `max(fuzz.ratio, fuzz.token_sort_ratio) / 100`, keep `≥ threshold`, round 4, sort `(-score, extracted, matched)`. Empty strings after normalization never match. `threshold` outside [0,1] → `ValueError`.
- **GOLDEN** `name_pairs.json`: list of `{extracted, first_name, last_name, should_match}` — ≥ 15 cases: accents, case, `Gonza1ez`, curly vs straight apostrophe, honorific, reversed order `"Gonzalez, Maria"`, negatives `Ana`/`Ana María Rodríguez`, `James Chen`/`Robert Chen`, `Maria Garcia`/`Mario Garza`.
- **TESTS** `tests/unit/domain/test_name_matching.py`: the 5 T-002 acceptance criteria + parametrized golden pairs at 0.90 + threshold 0.80 case + determinism (run twice, equal).
- **VALIDATE**: `uv run pytest tests/unit/domain/test_name_matching.py tests/unit/domain/test_names.py -q`
- **GATE + COMMIT** `feat(T-002): accent/case/noise-robust full-string name matching`

### ═══ T-003 OCR → PDF-point words ═══

#### CREATE `app/domain/geometry.py`, `app/domain/document.py`
- **TESTS** `tests/unit/domain/test_geometry.py`: T-003 AC2 numbers exactly (`(300,150,600,60)@300 → (72,36,144,14.4)`, `@150 → (144,72,288,28.8)`), negative values rejected, `union_box` correctness, `dpi=0` rejected.

#### CREATE `app/application/ports.py` (all three ports now — recognizer used from T-004)
- **VALIDATE**: `uv run mypy app`

#### CREATE `app/infrastructure/pymupdf_rasterizer.py`
- **IMPLEMENT**: `PyMuPdfRasterizer.probe(pdf)` — `with pymupdf.open(stream=pdf, filetype="pdf") as doc` → `PdfInfo(doc.page_count, doc.needs_pass)`; `FileDataError`/`RuntimeError` from open → `PdfUnreadable`. `render(pdf, dpi)` — same open; `needs_pass` → `PdfEncrypted`; for `i, page in enumerate(doc)`: `pix = page.get_pixmap(dpi=dpi)`; yield `PageImage(i, page.rect.width, page.rect.height, dpi, pix.tobytes("png"))`. Generator keeps the doc open only while iterating (`with` inside the generator).
- **GOTCHA**: never `import fitz`.

#### CREATE `app/infrastructure/tesseract_ocr.py`
- **IMPLEMENT**: `TesseractOcrEngine(languages, confidence_floor, timeout_seconds, tesseract_cmd)`. In `__init__` set `pytesseract.pytesseract.tesseract_cmd` when given. `recognize(image)`: `with Image.open(io.BytesIO(image.png)) as img:` → `image_to_data(img, lang=..., config="--psm 3", timeout=..., output_type=Output.DICT)`. Map rows where `text.strip()` and `float(conf) ≥ floor` → `Word(text.strip(), pixels_to_points(left, top, width, height, image.dpi), float(conf), (block, par, line))`. Clamp boxes to the page (`min(x+w, width_pt)`). `TesseractNotFoundError` → `OcrUnavailable("Tesseract binary not found: ...")`; `RuntimeError` timeout → `OcrUnavailable`; `pytesseract.TesseractError` → `OcrUnavailable`. Log `ocr_page_empty` (page index) when no words; log `ocr_page_completed` (`page_index`, `word_count`, `duration_ms`).
- **GOTCHA**: pass the PIL image, not a path — nothing touches disk (pytesseract itself writes temp files in its own scope and cleans them; the leak test covers it).

#### CREATE `tests/fakes/` (`FakeRasterizer(pages: int)`, `FakeOcrEngine(pages: dict[int, list[Word]])`, `FakeRecognizer(spans_by_text)` with call counters)

#### TESTS
- `tests/unit/application/test_ocr_all_pages.py` — AC1 via a tiny helper the use case will reuse: iterate `rasterizer.render` → `ocr.recognize`; assert indexes `[0,1,2]` and 3 OCR calls. (Lives as a private function in `app/application/extract_names.py` — `_read_pages(rasterizer, ocr, pdf, dpi) -> list[Page]` — created now, `ExtractNames` added in T-006.)
- `tests/integration/test_pymupdf_rasterizer.py` — real samples: page counts 1/2/2, sizes 612×792; garbage bytes → `PdfUnreadable`; AES-encrypted PDF (built in test) → `PdfEncrypted` on render, `encrypted=True` on probe.
- `tests/integration/test_tesseract_ocr.py` — AC3 (all boxes in page; memo page 0 contains `Margaret`, `Thompson`), AC4 (`Thompson` at 150 vs 300 DPI within 2 pt), missing binary (`tesseract_cmd="C:/nope/tesseract.exe"`) → `OcrUnavailable`, temp-dir listing unchanged before/after (AC5).
- `tests/conftest.py` — `settings` fixture reading `.env`/env; skip integration tests with a clear reason if Tesseract isn't found (`shutil.which` or configured path).
- **VALIDATE**: `uv run pytest -m integration tests/integration -q` (with `DOCINTEL_TESSERACT_CMD` set in `.env`).
- **GATE + COMMIT** `feat(T-003): OCR every page into words with PDF-point boxes`

### ═══ T-004 Person recognition + golden set + S1 ═══

#### CREATE `app/infrastructure/spacy_recognizer.py`
- **IMPLEMENT**: `SpacyPersonNameRecognizer(model_name)`: `spacy.load(model_name, disable=["lemmatizer"])` in `__init__`; `OSError` → `NerModelUnavailable`. `recognize(text)`: `[strip_leading_honorific(PersonSpan(e.start_char, e.end_char, e.text)) for e in doc.ents if e.label_ in {"PERSON", "PER"}]`; drop spans whose stripped text is empty.

#### CREATE `app/domain/page_text.py` (needed here so eval uses the same text as T-005)
- **IMPLEMENT**: `build_page_text(page) -> PageText`: iterate words; separator `" "` within the same `line_key`, `"\n"` when it changes; record spans.
- **TESTS** `tests/unit/domain/test_page_text.py`: T-005 AC1 round-trip, separators, empty page → `""`.

#### CREATE `tests/golden/persons.json`
- **IMPLEMENT** (hand-labelled from the scans, names without honorific, in reading order):
  - `company_memo.pdf` p0: Margaret Thompson, Robert Chen, Sarah Williams, James Anderson, Maria Garcia, David Nakamura, Patricia Okonkwo, Margaret Thompson (8)
  - `meeting_minutes.pdf` p0: Richard Hernandez, Elizabeth Park, Thomas Muller, Aisha Patel, Kevin O’Brien, Jennifer Liu, Carlos Mendoza, Richard Hernandez, Jennifer Liu, Elizabeth Park, Thomas Muller, Elizabeth Park, Aisha Patel, Kevin O’Brien (14)
  - `meeting_minutes.pdf` p1: Thomas Muller, Yuki Tanaka, Alexander Popov, Richard Hernandez, Catherine Dubois, Aisha Patel, Kevin O’Brien, Richard Hernandez, Jennifer Liu, Richard Hernandez (10)
  - `research_report.pdf` p0: Olivia Chambers, Benjamin Foster, Priya Sharma, Lucas Zimmermann, Fatima Al-Rashidi, Christopher Wong, Anna Kowalski, Michael O’Sullivan, Elena Volkov, Raj Krishnamurthy, Priya Sharma, Hans Weber (12)
  - `research_report.pdf` p1: Fatima Al-Rashidi, James Chen, Benjamin Foster, Anna Kowalski, Christopher Wong, Benjamin Foster, Fatima Al-Rashidi, Michael O’Sullivan, Fatima Al-Rashidi, Olivia Chambers, Margaret Thompson (11)
  - `negatives`: Atlas, NovaTech Solutions, ETH Zurich, Stanford University, London, CTO, National Science Foundation, Forbes
- **VERIFY** while labelling by re-reading the page renders; total 55 occurrences.

#### CREATE `scripts/eval_ner.py`
- **IMPLEMENT**: build `Settings`, `PyMuPdfRasterizer`, `TesseractOcrEngine`, `SpacyPersonNameRecognizer(--model or settings.ner_model)` directly (scripts are direct, CONSTITUTION §1.4). Per page: `build_page_text` → recognize → compare predicted vs golden as multisets of `normalize_name` (TP = Σ min counts). Print per-document + total P/R, FP list, FN list, and any negative that appeared. Exit 1 if P or R < 0.90 or any negative appears.
- **TESTS** `tests/integration/test_spacy_recognizer.py` — T-004 AC1, AC2 (offsets slice exactly), unknown model → `NerModelUnavailable`. `tests/unit/test_golden_set.py` — AC3: 5 pages present, 55 occurrences, negatives listed.
- **S1**: run `uv run python scripts/eval_ner.py`; if it fails with `sm`, `uv add` the `en_core_web_trf` wheel **only after writing ADR-013** and rerun with `--model en_core_web_trf`. If neither passes → stop and report (ticket alt-flow: record open question in TRD §16, do not proceed to T-006 silently). Write numbers + date + decision into TRD §15 S1.
- **VALIDATE**: `uv run python scripts/eval_ner.py` exits 0.
- **Amendment (S1 result, 2026-10-21):** `sm` met P/R (0.912/0.945) but leaked `Atlas` and
  `Forbes`, failing TRD §1's zero-leak criterion. `md` (0.929/0.945) leaked `Atlas`. `lg`
  passed (1.000/0.982, no leaks) without torch, so it was adopted via **ADR-013** instead
  of `trf`; `ner_model` default is now `en_core_web_lg` and its wheel replaces `sm`.
- **GATE + COMMIT** `feat(T-004): spaCy PERSON recognizer, golden set and NER eval (S1)`

### ═══ T-005 Locate occurrences ═══

#### CREATE `app/domain/persons.py` (if not already from T-004) and `app/domain/alignment.py`
- **IMPLEMENT**: `locate_occurrences(page, page_text, spans) -> list[NameOccurrence]`: for each span, indexes `i` with `word_spans[i]` overlapping `[start,end)` (`ws < end and we > start`); none → log `alignment_span_unmatched` (page index, start, end) and skip; group selected words by `line_key` preserving order; one `NameOccurrence(span.text, page.index, union_box(group boxes))` per group. Final sort: `(page_index, box.y, box.x)`.
- **TESTS** `tests/unit/domain/test_alignment.py`: T-005 AC2 (`From: Margaret Thompson, CEO`), AC3 (3× Richard Hernandez on 3 lines → 3 boxes top-to-bottom), AC4 (wrap → 2 occurrences, heights ≤ line height), AC5 (boxes are exact unions, inside page), unmatched span skipped + logged (caplog, no name in record).
- **VALIDATE**: `uv run pytest tests/unit/domain -q`
- **Amendment (T-005 execution):** occurrences are ordered by their offset in the page
  text (reading order — T-005 "position in the page text") instead of `(box.y, box.x)`,
  which could reorder two names on the same line whose word tops differ by a point. The
  occurrence name is the span text with whitespace collapsed (`"David
Nakamura"` →
  `"David Nakamura"` for a wrapped name).
- **GATE + COMMIT** `feat(T-005): char-offset alignment of names to OCR word boxes`

### ═══ T-006 `/api/extract` end to end ═══

#### UPDATE `app/application/extract_names.py`
- **IMPLEMENT**: `ExtractNames(rasterizer, ocr, recognizer, dpi: int, fuzzy_threshold: float)`; `execute(pdf: bytes, requested: Sequence[RequestedName]) -> ExtractionResult`: `_read_pages` → per page `build_page_text` → `recognizer.recognize(text)` → `locate_occurrences` → `match_names(unique occurrence names, requested, threshold)`. Time each stage with `perf_counter`; log `extraction_completed` with `document_sha256` (first 12 hex), `page_count`, `occurrence_count`, `unique_name_count`, `match_count`, `ocr_ms`, `ner_ms`, `align_ms`, `match_ms`.
- **TESTS** `tests/unit/application/test_extract_names.py`: AC4 (2-page fakes, no FastAPI import in the module — assert via `sys.modules` is not needed; import-linter covers it), stage order, empty requested → no matches, log record has no names.

#### CREATE `app/api/mapping.py`, UPDATE `app/api/extract.py`, `app/api/dependencies.py`, `app/main.py`
- **IMPLEMENT**: route `@router.post("/extract", response_model=ExtractionResponse)` as sync `def`, params `pdf_file: UploadFile | None = File(None)`, `names: str = Form("[]")`. T-006 minimal parsing: `pdf_file is None` → `UploadMissing`; `json.loads` + `TypeAdapter(list[NamePair])` failures → `NamesInvalid`; bytes = `pdf_file.file.read()` (T-007 replaces with the capped reader). Call `extract_names.execute`, map: `ExtractedName(name=o.name, bounding_box=BoundingBox(page_number=o.page_index, x=..., ...))`, `FuzzyMatch(...)`. OpenAPI `description` states: boxes in PDF points, top-left origin, 0-based pages. `Container` gains `rasterizer` and `extract_names`; `build_container` instantiates `PyMuPdfRasterizer`, `TesseractOcrEngine(settings...)`, `SpacyPersonNameRecognizer(settings.ner_model)`, `ExtractNames(...)`.
- **GOTCHA**: `names: str = Form("[]")` — a missing `names` field means "no names to check" (documented decision; README shows it as a field but an empty check list is still a valid request).
- **TESTS** `tests/unit/api/test_extract_route.py` (fake container): DTO mapping, malformed names → 422 `names_invalid`, missing file → 422 `pdf_file_missing`, `OcrUnavailable` from fake → 503 `ocr_unavailable`.
- `tests/e2e/test_extract_samples.py` (`integration`): AC1 (each sample, schema-valid, pages present, boxes within 612×792), AC2 (`Richard Hernandez` entries == 5 in `meeting_minutes.pdf`, distinct boxes), AC3 (Margaret Thompson + Maria Garcia matched ≥ 0.90, Ana Lopez not).

#### CREATE `scripts/eval_boxes.py`
- **IMPLEMENT**: for each sample, run the real `ExtractNames`; for each occurrence: render the page clip `page.get_pixmap(dpi=300, clip=pymupdf.Rect(x-2, y-2, x+w+2, y+h+2))` → `image_to_data`/`image_to_string` with `--psm 7` → `normalize_name` compare with the reported name (`fuzz.ratio ≥ 90`, allowing the crop to include trailing punctuation). Report pass rate (must be 100 %) and occurrence recall vs `tests/golden/persons.json` (≥ 0.95, multiset per page). Exit 1 otherwise. (Script imports pymupdf directly — scripts are outside `app/`.)
- **VALIDATE**: `uv run python scripts/eval_boxes.py` exits 0.
- **GATE + COMMIT** `feat(T-006): POST /api/extract end to end with box self-check eval`

### ═══ T-007 Upload validation ═══

#### CREATE `app/api/upload.py`
- **IMPLEMENT**: `read_pdf_upload(upload: UploadFile | None, max_bytes: int, rasterizer: PdfRasterizer, max_pages: int) -> bytes`, order exactly as T-007 table: missing → `UploadMissing`; `data = upload.file.read(max_bytes + 1)`; `len == 0` → `UploadEmpty`; `> max_bytes` → `UploadTooLarge(f"max {max_bytes} bytes")`; `not data.startswith(b"%PDF-")` → `UploadIsNotPdf`; `info = rasterizer.probe(data)` (raises `PdfUnreadable`); `info.encrypted` → `PdfEncrypted`; `info.page_count > max_pages` → `PdfTooManyPages`. Always `upload.file.close()` in `finally`. Log `upload_rejected` (`code`, `size_bytes`) on each rejection via the error handler (one place).
- **UPDATE** `app/api/extract.py`: use `read_pdf_upload` (via `Container.settings` + `Container.rasterizer`); names validation unchanged but message names the failing field.
- **TESTS** `tests/unit/api/test_upload_validation.py` with fake rasterizer (counts `probe`/`render` calls; OCR fake asserts never called): AC1 (text as `fake.pdf` → 415; real PDF bytes generated by pymupdf in-test as `scan.txt`/`text/plain` → 200), AC2 (0 bytes → 400; `max+1` → 413 with settings override `max_upload_bytes=1024`), AC3 (encrypted → 422 `pdf_encrypted`; `b"%PDF-1.7 broken"` → 422 `pdf_unreadable`; `max_pages+1` pages with `max_pages=2` → 413 `pdf_too_many_pages`) — these three use the **real** `PyMuPdfRasterizer` (pure Python, no Tesseract) with a fake OCR, AC4 (4 malformed `names` values → 422 `names_invalid`), AC5 (`tempfile.gettempdir()` listing identical before/after an accepted and an oversized upload).
- **VALIDATE**: `uv run pytest tests/unit/api -q`
- **GATE + COMMIT** `feat(T-007): content-based upload validation and name-list validation`

### ═══ Epic close ═══
- UPDATE `docs/specs/extraction/_manifest.md` + `_changelog.md`: note implementation commits per ticket (states stay `approved`).
- Walk `docs/requirements-traceability.md` rows for extraction; every "Verified by" must point at an existing test.

---

## TESTING STRATEGY

### Unit Tests (fast suite, no Tesseract/spaCy model needed)
Domain (geometry, names, matching, page text, alignment) with hand-built values, no mocks. Application with `tests/fakes/`. API with `TestClient(create_app(build_container=fake))`. Infrastructure settings/logging.

### Integration Tests (`-m integration`)
Real PyMuPDF on samples + generated PDFs; real Tesseract; real spaCy model; e2e over HTTP on `sample_pdfs/`. Auto-skipped with a clear reason when Tesseract isn't available.

### Evals (`scripts/`)
`eval_ner.py` (P/R ≥ 0.90, no negatives), `eval_boxes.py` (100 % box self-check, occurrence recall ≥ 0.95). Golden data in `tests/golden/`.

### Edge Cases
Curly apostrophes, hyphenated surnames, honorifics, repeated names, names wrapping lines, names followed by commas, blank pages, encrypted/corrupt/oversized/mis-extensioned uploads, empty name list, missing Tesseract, unknown spaCy model, threshold boundaries.

### E2E / Browser Automation
N/A for this epic — no UI. The audit viewer (TRD P3) will carry the agent-browser validation.

---

## VALIDATION COMMANDS (the gate — run all at the end of every ticket)

### Level 1: Syntax & Style
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run lint-imports
```
### Level 2: Unit Tests
```bash
uv run pytest -m "not integration" -q
```
### Level 3: Integration Tests (from T-003 on)
```bash
uv run pytest -m integration -q
```
### Level 4: Manual Validation (from T-006 on)
```bash
uv run uvicorn app.main:app --port 8000 &
curl -s localhost:8000/health
curl -s -F pdf_file=@sample_pdfs/company_memo.pdf -F 'names=[{"first_name":"Margaret","last_name":"Thompson"}]' localhost:8000/api/extract
curl -s -o /dev/null -w "%{http_code}\n" -F pdf_file=@README.md localhost:8000/api/extract   # expect 415 after T-007
```
### Level 5: Evals (from T-004 / T-006)
```bash
uv run python scripts/eval_ner.py
uv run python scripts/eval_boxes.py
```

---

## ACCEPTANCE CRITERIA

- [ ] Every acceptance criterion of T-001…T-007 has a passing test or eval.
- [ ] Gate (Levels 1–3) green after each ticket; evals exit 0.
- [ ] `app/models/schemas.py` unchanged (`git diff 7acb727 -- app/models/schemas.py` empty).
- [ ] No vendor import outside `app/infrastructure/` (import-linter), no literal config values outside `Settings`.
- [ ] Logs contain no person names or document text.
- [ ] 7 commits, one per ticket, conventional messages with attribution lines.

## COMPLETION CHECKLIST

- [ ] All tasks completed in order, TDD per task
- [ ] Gate green per ticket; evals pass
- [ ] Manual curl checks done (Level 4)
- [ ] TRD §15 S1 updated with measured numbers
- [ ] Manifest/changelog updated

---

## NOTES

- **Design ratchet:** T-001, T-003, T-004, T-005 were flagged "Design: likely-needed". Their decisions are pinned here in SHARED CONTRACTS (ports, domain types, errors, settings, logging, layering) and come from TRD ADR-001…ADR-005 + ADR-012; the human reviews them once with this plan instead of four separate `/design` gates. Any change to these contracts during execution = stop and amend the plan (no silent drift).
- **Dependency trim:** RAG libraries removed from runtime deps until the RAG epic (avoids pulling torch now); recorded later in `DECISIONS.md`.
- **Missing `names` field → `[]`:** lenient, documented in the route description.
- **Line-wrapped names** produce one entry per line segment (ADR-004); the samples have none, covered by unit test.
- **Risk:** Tesseract may split/merge tokens differently from spaCy's tokenizer — alignment works on char overlap, so a token like `Thompson,` is still selected whole; the box self-check eval tolerates trailing punctuation.
- **Risk:** S1 may fail on OCR noise; the alt-flow stops before T-006.
- **Confidence:** 8/10 for one-pass success (main uncertainty: NER metrics on real OCR text, and import-linter `|` syntax).
