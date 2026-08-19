# Audit — Dependencies, Configuration, Logging, Test Suite

**Repo:** `/home/cristhian/Documents/ML-Engineer-test`
**Branch:** `feature/document-intelligence-service` @ `d32153a` **+ uncommitted working-tree changes** (audited as on disk)
**Date:** 2026-08-18
**Auditor scope:** `pyproject.toml`, `uv.lock`, `app/config.py`, `app/main.py`, `app/models/domain.py`, `tests/**` — "does it actually run here".

---

## Scope

I own the environment-and-reproducibility half of this review:

1. Running the test suite verbatim and diagnosing anything that fails or fails to collect.
2. Environment reality check — is `tesseract` present, is `en_core_web_sm` loadable, is everything `pyproject` declares actually installed.
3. Dependency completeness/hygiene and `uv.lock` status.
4. Configuration centralization and environment-overridability (grep of the whole `app/` tree for values that should be settings).
5. Logging: structure, single configuration point, request context, `print()`/PII leaks.
6. Test suite judgement against the five graded traps, plus dead/over-mocked/slow tests.

Out of scope and deliberately not reported: the stubbed RAG half (`app/services/{rag,vector,embedding}_service.py`, `app/api/rag.py`), and the internal algorithmic correctness of `ocr_service` / `bbox_service` / `ner_service` / `fuzzy_service` (other auditors own those). I read those files only to verify config wiring and logging.

---

## Verdict

**This is a strong submission and it genuinely runs.** The full suite is green — `59 passed in 2.66s` — with zero collection errors, zero warnings, no skips, and no test that loads a heavy model at import time. Configuration is exemplary: every tunable the rubric names (DPI, OCR language, timeout, confidence floor, spaCy model name, fuzzy threshold, max upload size, max names, log level) lives in a single validated `pydantic-settings` class with an `env_prefix`, a cached `get_settings()`, and a committed `.env_example`; my grep of `app/` found **no** hardcoded magic number or model name outside `app/config.py`. Logging is thorough and disciplined — no `print()`, no bare `except: pass`, no filename or document text logged, and every stage emits page counts and timings. I proved the pipeline works end to end with real spaCy, real bbox mapping and real fuzzy matching by injecting only a fake `image_to_data`: page 0 was OCR'd, boxes came back in PDF points (`x=60.0` from `left=250 @ 300 DPI`, i.e. `×0.24`), and `Maria Gonzalez` matched `María González` at score `1.0`. The blockers are not code-logic bugs, they are **delivery and reproducibility**: `uv.lock` is still untracked and both `DESIGN.md` and `DECISIONS.md` — explicit README deliverables worth 20% of the rubric — do not exist. Beyond that, the `tesseract` binary is absent on this machine so every real request 503s (handled gracefully, but undocumented and unconfigurable), there are no retries anywhere despite the spec asking for them, logs carry no request-correlation ID, and six real validation branches plus the entire real-OCR path have no test at all.

---

## Findings

| ID | Sev | File:line | Problem | Recommended fix |
|---|---|---|---|---|
| D1 | **P0** | `uv.lock` (untracked); `README.md:129` | README says verbatim "Commit the resulting `uv.lock`." `git status --porcelain` reports `?? uv.lock` — it is present on disk (775 KB, 146 packages) but **never committed**. Compounded by `pyproject.toml:8-28`, where all 14 dependencies are declared with **zero version constraints**. A reviewer cloning the branch gets a fully floating dependency graph and cannot reproduce this venv. | `git add uv.lock && git commit`. `uv.lock` is not in `.gitignore`, so this is a one-line fix. Optionally add lower bounds (`fastapi>=0.115`, `pydantic>=2.9`, `spacy>=3.8`) so the lock is regenerable. |
| D2 | **P0** | repo root — `DESIGN.md`, `DECISIONS.md` both missing | `README.md:133-138` lists Deliverables 2 and 3 as `DESIGN.md` and a short `DECISIONS.md`. Neither file exists (`ls` confirms only `README.md`). The rubric at `README.md:141-150` weights "Design document 5%" and "Code quality & decisions 15%". `pyproject.toml:7` also tells the candidate to justify dependency choices in `DECISIONS.md`. This is a guaranteed, avoidable loss of graded points on otherwise good work. | Write both. `DECISIONS.md` should cover: why `thefuzz` full-string ratio over partial, why 300 DPI, why Protocols over ABCs, why `sentence-transformers`/`chromadb` were left in, and the AI-tool disclosure required by `README.md:169-174`. |
| D3 | **P1** | environment; `app/services/ocr_service.py:35`; `app/config.py:19-22` | The `tesseract` binary is **not installed** (`tesseract --version` → `command not found`). Every real request to `/api/extract` therefore fails. The code degrades correctly (503, clean message, no leaked internals — see Evidence §3), but (a) the candidate added no documentation of the system-level dependency, and (b) `Settings` has **no `tesseract_cmd` path field**, so on a box where the binary exists off-`PATH` there is no supported way to point `pytesseract` at it. The rubric explicitly names "tesseract lang/**path**" as config that should be centralized. | Add `tesseract_cmd: str | None = None` to `Settings`, and in `TesseractOCRService.__init__` set `pytesseract.pytesseract.tesseract_cmd` when it is provided. Document `apt-get install tesseract-ocr` (or `brew install tesseract`) in `DESIGN.md`, and add a `/health` readiness probe that surfaces `pytesseract.get_tesseract_version()`. |
| D4 | **P1** | `app/services/ocr_service.py:93`; `app/config.py:21`; whole `app/` tree | **No retries anywhere in the extract path.** The spec asks for "timeouts, **retries**, meaningful failure modes". The timeout is present and configurable (`ocr_timeout_seconds`, passed at `ocr_service.py:93`) and failure modes are meaningful, but `grep -rn -i "retry\|retries\|backoff\|tenacity" app/ pyproject.toml` returns only a comment inside the stubbed `rag_service.py:4`. There is no retry logic and no retry setting. A single transient Tesseract timeout fails the whole multi-page document. | Add `ocr_max_attempts: int = Field(default=2, ge=1)` and `ocr_retry_backoff_seconds: float` to `Settings`, and wrap the per-page `self._image_to_data(...)` call in a bounded retry with backoff. Shared with the services auditor. |
| D5 | **P1** | `app/main.py:25-52`; `app/api/validation.py:179` (see concurrency note); `app/services/extraction_service.py:43,74` | **No request-correlation ID.** The middleware logs method/path/status/duration and the services log page counts and timings, but nothing ties them together. Under any concurrency the interleaved `OCR page completed: page=0` and `Request completed: POST /api/extract` lines cannot be attributed to a request. The rubric names "request id" specifically. Logging is also key=value embedded in human-readable strings rather than machine-parseable structured output. | Generate a UUID per request in the middleware, put it in a `ContextVar`, and attach it via a `logging.Filter` so every record carries `request_id`. Optionally emit JSON via a formatter. Existing call sites need no change. |
| D6 | **P1** | `pyproject.toml:23-25` | `sentence-transformers` and `chromadb` are hard runtime dependencies but are used **only** by the deliberately-stubbed RAG half. They drag in `torch` (1.1 GB) plus the full NVIDIA CUDA wheel set; the resulting `.venv` is **5.3 GB**. A reviewer who only wants to grade `/api/extract` waits through a multi-GB download for code that raises `NotImplementedError`. | Move both to `[project.optional-dependencies] rag = [...]`, keeping the graded extract path a lightweight install. Note the choice in `DECISIONS.md`. If they stay required, pin the CPU-only torch index in `[tool.uv.sources]`. |
| T1 | **P1** | `tests/` — no such test | **Six live validation branches have zero coverage**: `max_names` limit (`validation.py:47-54`), password-protected PDF (`:94-99`), zero-page PDF (`:100-105`), corrupt/unreadable PDF via `FileDataError` (`:108-113`), empty upload (`:143-148`), and the post-read oversize branch (`:149-156`). Note the existing `test_file_extension_does_not_make_non_pdf_content_valid` only exercises the `%PDF-` signature check at `:85`, not the `pymupdf` parse failure path. Every one of these is cheap to test and is exactly the "input validation" the rubric grades. | Add parametrized cases to `tests/test_request_validation.py` calling `read_and_validate_pdf` / `validate_pdf_content` directly with: `b""`, a truncated `b"%PDF-1.4 garbage"`, a `pymupdf`-built encrypted PDF, and a `names` array longer than `max_names`. |
| T2 | **P1** | `tests/` — no such test | **Nothing in the suite ever executes the real OCR path.** Every OCR test injects a fake `image_to_data` (`tests/test_ocr_service.py:39-44`), and the three files in `sample_pdfs/` are never opened by any test. The suite would stay fully green if `pytesseract` were broken, which is precisely the failure this machine actually has. | Add one integration test against `sample_pdfs/company_memo.pdf` guarded by `@pytest.mark.skipif(shutil.which("tesseract") is None, ...)` asserting page 0 yields non-empty text and at least one PERSON box inside the page rectangle. Register an `integration` marker so it can be deselected in CI. |
| C1 | P2 | `app/api/extract.py:7` | `from starlette.concurrency import run_in_threadpool` imports `starlette` directly, but `starlette` is **not declared** in `pyproject.toml:8-28` — it is relied upon as a transitive dependency of `fastapi`. That is a latent break if FastAPI ever vendors or repins it. | Either declare `starlette` explicitly, or use the re-export `from fastapi.concurrency import run_in_threadpool`. |
| C2 | P2 | `pyproject.toml` (no `[tool.pytest.ini_options]`; file ends at line 41) | There is **no pytest configuration at all**. The suite passes only because every async test carries an explicit `@pytest.mark.asyncio` and pytest 9 happens to anchor rootdir on `pyproject.toml`. Nothing pins `asyncio_mode`, `testpaths`, `--strict-markers`, or `filterwarnings`, so an unmarked async test added later would silently not run. | Add `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, `asyncio_mode = "strict"`, `addopts = "--strict-markers"`, `filterwarnings = ["error"]`, and a `markers = ["integration: ..."]` entry for T2. |
| C3 | P2 | `app/main.py:13-18` | `get_settings()` and `logging.basicConfig(...)` execute at **module import time**. Importing `app.main` (which `tests/test_logging.py:6` and `tests/test_request_validation.py:12` both do) mutates global logging state as a side effect, and `basicConfig` is a silent no-op if uvicorn/gunicorn already installed a root handler — so `DOC_INTEL_LOG_LEVEL` can be quietly ignored in production. | Move logging setup into a `configure_logging(settings)` function called from a FastAPI `lifespan` handler, or use `logging.config.dictConfig` with `disable_existing_loggers=False`. |
| C4 | P2 | `app/config.py:30` | `env_file=".env"` is resolved relative to the **current working directory**, so settings load differently depending on where the process is started. | Anchor it: `env_file=Path(__file__).resolve().parent.parent / ".env"`. |
| C5 | P2 | `.env_example` (filename) | The file is named `.env_example`, not the conventional `.env.example`. This is accidentally load-bearing: `.gitignore` ignores `.env.*`, so renaming it to the conventional name would silently **untrack** it. | Keep the current name and add an explicit `!.env.example` negation to `.gitignore` before renaming, or leave as-is and mention it in `DESIGN.md`. |
| T3 | P2 | `tests/test_config.py:7-30` | `get_settings()`'s `@lru_cache` (`app/config.py:42`) is never asserted, and no test covers `.env` file loading. `test_dependencies.py:8-29` proves the *service* is built once, but not that settings are cached. | Add `assert get_settings() is get_settings()`, plus a `tmp_path`-based `.env` test using `Settings(_env_file=<tmp>)`. |

**Areas I checked and found nothing wrong:** hardcoded magic numbers/strings in `app/` (none outside `app/config.py` — see Evidence §5); `print()` statements (none); silent `except: pass` (none — all three `except Exception` blocks log with `exc_info`); PII/document-content logging (none — only sizes and counts are logged); missing/uninstalled Python dependencies (all 17 checked import cleanly); `app/models/domain.py` (invariant validation is sound and well-tested by `tests/test_domain_models.py`); over-mocked tests asserting nothing (none found — every test makes a real assertion); slow tests loading real models (none — slowest test is 0.01s).

---

## Graded-trap coverage

| Trap | Status | Test |
|---|---|---|
| OCR processes **every** page including page 0 | **COVERED** | `tests/test_ocr_service.py::test_ocr_processes_every_page_including_page_zero` — counts calls (`== 2`) and asserts `page_number == [0, 1]`. Reinforced by `test_extraction_service.py::test_pipeline_processes_every_page_and_returns_fixed_response` (`ner.pages == [0, 1]`) and `test_domain_models.py::test_ocr_document_requires_all_pages_in_zero_based_order`. |
| Boxes in **PDF points**, not image pixels | **COVERED** | `tests/test_ocr_service.py::test_ocr_converts_pixel_boxes_to_pdf_points_and_normalizes_confidence` — at `ocr_dpi=144` (scale `72/144 = 0.5`) it asserts `left=20 → x=10`, `top=40 → y=20`, `width=60 → 30`, `height=20 → 10`. A genuine unit-conversion assertion, not a tautology. |
| Case- **and** accent-insensitive matching | **COVERED** | `tests/test_fuzzy_service.py::test_fuzzy_matching_is_case_accent_and_punctuation_insensitive` — `"MARÍA-GONZÁLEZ"` vs `Maria Gonzalez` → score `1.0`. |
| **Full-string** similarity, not substring/partial | **COVERED** | `tests/test_fuzzy_service.py::test_fuzzy_matching_uses_full_string_not_substring_similarity` — asserts `"Maria"` vs `Maria Gonzalez` returns `()`. This is the exact test that catches `partial_ratio` misuse. |
| Non-PDF rejected by **content**, not extension | **COVERED** | `tests/test_request_validation.py::test_file_extension_does_not_make_non_pdf_content_valid` — filename `scan.pdf` + `Content-Type: application/pdf` + body `b"not a pdf"` → `415`. Correctly proves neither extension nor declared MIME type is trusted. (Only the signature branch; see T1 for the `pymupdf`-parse branch.) |
| End-to-end through FastAPI with heavy models mocked | **COVERED** | `tests/test_extract_endpoint.py` (4 tests) and `tests/test_request_validation.py::test_valid_multipart_request_reaches_pipeline` — real ASGI stack via `httpx.ASGITransport`, `app.dependency_overrides[get_extraction_service]`, always cleared in a `finally`. Also covers 503/500 error mapping and asserts internal exception text never leaks (`test_extract_endpoint_hides_unexpected_failure_details`). |

All six traps are covered by tests that would actually fail if the trap were mis-implemented. This is the strongest part of the submission.

---

## Evidence

### 1. Test suite — full run, verbatim

```
$ cd /home/cristhian/Documents/ML-Engineer-test && uv run --no-sync pytest -q
...........................................................              [100%]
59 passed in 2.66s
```

**59 passed, 0 failed, 0 errors, 0 skipped, 0 warnings.** No collection errors. Re-run with `-r a` produced no extra summary lines (no warnings, no skips).

Per-file breakdown and timing:

```
$ uv run --no-sync pytest -q -v --durations=15
platform linux -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/cristhian/Documents/ML-Engineer-test
configfile: pyproject.toml
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None
collected 59 items

tests/test_bbox_service.py .......                                       [ 11%]
tests/test_config.py ...                                                 [ 16%]
tests/test_dependencies.py ..                                            [ 20%]
tests/test_domain_models.py ........                                     [ 33%]
tests/test_extract_endpoint.py ....                                      [ 40%]
tests/test_extraction_service.py ....                                    [ 47%]
tests/test_fuzzy_service.py ..........                                   [ 64%]
tests/test_logging.py .                                                  [ 66%]
tests/test_ner_service.py ......                                         [ 76%]
tests/test_ocr_service.py ......                                         [ 86%]
tests/test_request_validation.py .......                                 [ 98%]
tests/test_service_protocols.py .                                        [100%]

============================= slowest 15 durations =============================
0.01s call     tests/test_extract_endpoint.py::test_extract_endpoint_delegates_to_injected_service
0.01s call     tests/test_extract_endpoint.py::test_extract_endpoint_maps_dependency_failure_to_503
...
(9 durations < 0.005s hidden.)
============================== 59 passed in 2.71s ==============================
```

Note `configfile: pyproject.toml` is reported even though the file contains **no** `[tool.pytest.ini_options]` table — pytest 9 anchors rootdir on `pyproject.toml` regardless. See C2. Slowest test is 0.01s: **no test loads a real model** (spaCy is only loaded by my out-of-band script below, never by the suite).

### 2. Environment reality check

```
$ tesseract --version
bash: line 1: tesseract: command not found          # ← D3

$ uv run --no-sync python -c "import spacy; nlp=spacy.load('en_core_web_sm'); ..."
SPACY OK 3.8.0
(Maria Gonzalez, John Smith)                        # model IS downloaded and loadable
```

All declared dependencies resolve inside `.venv` (`importlib.util.find_spec`):

```
fastapi OK | uvicorn OK | multipart OK | pydantic OK | pydantic_settings OK
pytesseract OK | pymupdf OK | fitz OK | PIL OK | spacy OK | thefuzz OK
Levenshtein OK | sentence_transformers OK | chromadb OK | httpx OK
pytest OK | pytest_asyncio OK
```

Install weight (D6):

```
$ du -sh .venv                                   → 5.3G
$ du -sh .venv/lib/python3.12/site-packages/torch → 1.1G
$ ls -d .venv/.../nvidia*                        → nvidia, nvidia_cublas-13.1.1.3, nvidia_cuda_cupti-13.0.85, ...
$ grep -c "^name = " uv.lock                     → 146 packages
```

### 3. Real end-to-end request with the real pipeline (tesseract absent)

Posted `sample_pdfs/company_memo.pdf` through `TestClient` with **no mocks**:

```
pytesseract.pytesseract.TesseractNotFoundError: tesseract is not installed or it's not in your PATH.
The above exception was the direct cause of the following exception:
  File ".../app/services/ocr_service.py", line 97, in _extract_page
    raise OCRProcessingError(f"OCR failed on page {page_number}") from exc
app.services.errors.OCRProcessingError: OCR failed on page 0
INFO|app.main|Request completed: POST /api/extract returned 503 in 737.80 ms

STATUS: 503
BODY: {"detail":"an extraction dependency is unavailable"}
```

**This is correct, well-engineered behaviour**: the low-level cause is chained (`from exc`) and fully logged server-side, the page number is identified, and the client gets a clean 503 with no internal detail leaked. The finding (D3) is the missing binary + missing docs + missing `tesseract_cmd` setting, **not** the error handling.

### 4. Real end-to-end pipeline with only `image_to_data` faked

To prove the rest of the stack actually works here, I ran the real `TesseractOCRService` (fake `image_to_data` only), real `SpacyNERService`, real `OCRBoundingBoxService`, real `TheFuzzMatchingService` at `ocr_dpi=300` on a 2-page 612×792 PDF:

```
INFO|app.services.ner_service|Loading NER model: model=en_core_web_sm
INFO|app.services.ocr_service|OCR started: pages=2, dpi=300, language=eng
INFO|app.services.ocr_service|OCR page completed: page=0, words=6, duration_ms=54.00
INFO|app.services.ocr_service|OCR page completed: page=1, words=3, duration_ms=49.93
INFO|app.services.ner_service|NER page completed: page=0, people=1, duration_ms=5.31
INFO|app.services.bbox_service|Bounding-box mapping completed: mentions=2, located=2
INFO|app.services.fuzzy_service|Fuzzy matching completed: extracted=2, candidates=2, matches=2
INFO|app.services.extraction_service|Extraction pipeline completed: pages=2, mentions=2, located=2, matches=2, duration_ms=126.88

{"extracted_names": [
   {"name": "Maria Gonzalez", "bounding_box": {"page_number": 0, "x": 60.0, "y": 48.0, "width": 43.2, "height": 7.2}},
   {"name": "John Smith",     "bounding_box": {"page_number": 1, "x": 36.0, "y": 48.0, "width": 43.2, "height": 7.2}}],
 "fuzzy_matches": [
   {"extracted_name": "Maria Gonzalez", "matched_name": "María González", "score": 1.0},
   {"extracted_name": "John Smith",     "matched_name": "john smith",     "score": 1.0}]}
```

Verified by hand: at 300 DPI the scale is `72/300 = 0.24`; the word `Maria` was fed at pixel `left=250` → `250 × 0.24 = 60.0` points. ✅ Points, not pixels. Page 0 present. ✅ Accent- and case-insensitive matching at `1.0`. ✅ The log line quality here is genuinely good — page counts and per-stage timings throughout.

### 5. Configuration centralization — grep results

```
$ grep -rn -E "^[A-Z_]{3,}\s*=" app/ --include=*.py
app/services/text_normalization.py:6:_NON_ALPHANUMERIC = re.compile(r"[\W_]+", flags=re.UNICODE)
```

The only module-level constant in the entire tree is a regex. Every service takes `Settings` by constructor injection and reads its knobs from it:

```
app/services/ocr_service.py:31-34   self._dpi / _language / _timeout_seconds / _min_confidence
app/services/ner_service.py:27      self._model_name  = settings.ner_model_name
app/services/fuzzy_service.py:20    self._threshold   = settings.fuzzy_match_threshold
app/services/bbox_service.py:23-24  self._match_threshold / _max_gap_factor
app/api/validation.py:176,178       settings.max_upload_size_bytes / max_names_per_request
app/main.py:16,22                   settings.log_level / app_name
```

`app/config.py:42` — `get_settings()` **is** `@lru_cache`d. `app/config.py:29-33` — `env_file=".env"`, `env_prefix="DOC_INTEL_"`, `extra="ignore"`. `.env_example` is tracked in git and documents all 12 variables. Fields carry real validation bounds (`ocr_dpi: ge=72, le=600`; thresholds `ge=0, le=1`), which `tests/test_config.py::test_invalid_threshold_is_rejected` exercises. **No hardcoded host, model name, threshold, or DPI exists outside `app/config.py`.** The only genuinely missing knob is `tesseract_cmd` (D3).

### 6. Logging hygiene

```
$ grep -rn "print(" app/ --include=*.py
(no output)                                          # ← no stray prints

$ grep -rn -E "except\s*:|pass\s*$" app/ --include=*.py
app/api/validation.py:163:        except Exception:      → followed by logger.warning(..., exc_info=True)
app/services/extraction_service.py:69: except Exception: → followed by logger.exception(...)
app/main.py:34:                   except Exception:      → followed by logger.exception(...) and re-raise
```

No silent swallowing. 55 logging call sites across 8 modules, all via `logging.getLogger(__name__)`. `app/api/validation.py:179` (see concurrency note) logs `pdf_size` and `names` **count** only — no filename, no document text, no name values. That is a deliberate and correct PII choice (it does mean the rubric's "filename" context is absent; I consider the privacy trade-off defensible and did not raise it as a finding).

### 7. Repo/delivery state

```
$ git status --porcelain
 M app/api/extract.py
 M app/services/bbox_service.py
 M app/services/ner_service.py
 M app/services/ocr_service.py
?? app/api/dependencies.py
?? app/services/errors.py
?? app/services/factory.py
?? uv.lock                       ← D1

$ ls *.md
README.md                        ← DESIGN.md and DECISIONS.md absent (D2)

$ git ls-files | grep -E "env|lock|md$"
.env_example
README.md
```

Note that three **new source files** (`dependencies.py`, `errors.py`, `factory.py`) and four modified ones are also uncommitted. They are other auditors' scope, but the delivery risk is mine to flag: **the branch as committed at `d32153a` does not contain the code I just tested.** Everything in this report describes the working tree.

I confirmed my commands did not mutate the repo: `uv.lock` mtime remained `ago 18 15:32` and `git status` was byte-identical before and after all runs. All scratch scripts were written to `/tmp`.

---

## Concurrency note (line-number drift)

Other auditors were editing this working tree while I ran. My readings are a snapshot taken during the audit; I re-verified at the end:

- `app/api/validation.py` was modified **after** I read it — a concurrent agent expanded the `File(...)`/`Form(...)` annotations inside `validate_extraction_request` starting at line 167. All validation-branch citations in this report (`:47-54`, `:85`, `:94-99`, `:100-105`, `:108-113`, `:143-156`, `:163`) are **above** that edit and remain accurate. The single citation that has drifted is the `logger.info("Extraction request validated: ...")` call, which I cite as `:179` and which now sits near `:201`.
- `app/models/schemas.py` was likewise modified after my initial `git status`.
- A re-run of the suite after those concurrent edits still passes: **`60 passed in 2.69s`** (one test was added by another agent since my `59 passed` baseline).

Every finding in this report was verified against the code as I read it, and none of the concurrent edits invalidate a finding.

---

## What is already good

- **The suite is green, fast, and honest.** 59 tests in 2.66s, no skips, no warnings, no collection errors, no test loading a real model. Every test I read makes a substantive assertion — I found **zero** tests that mock so heavily they assert nothing.
- **All six graded traps are covered by tests that would genuinely fail if broken** — especially `test_fuzzy_matching_uses_full_string_not_substring_similarity` and the DPI-scaling assertion in `test_ocr_converts_pixel_boxes_to_pdf_points_and_normalizes_confidence`.
- **Configuration is textbook.** One `Settings` class, `env_prefix`, cached accessor, validated bounds, tracked `.env_example`, constructor injection into every service, and not one magic number left in the tree.
- **Test isolation from the local environment is handled correctly**: tests consistently construct `Settings(_env_file=None, ...)` (e.g. `test_ocr_service.py:43`, `test_fuzzy_service.py:11`, `test_config.py:8`), so a developer's local `.env` cannot turn the suite red. This is a subtle detail most candidates miss.
- **Error-path testing is unusually thorough** — 503 vs 500 mapping, dependency-init failure, and an explicit test that internal exception text never reaches the client.
- **Domain invariants are enforced and tested.** `app/models/domain.py` validates zero-based contiguous page ordering (`:83-86`), word-to-page consistency (`:64-66`), offset spans within page text (`:67-68`), and normalized confidence (`:35-36`) — with 8 tests behind them. Frozen `slots=True` dataclasses throughout.
- **Logging discipline**: no prints, no silent excepts, no PII, per-stage page counts and millisecond timings, correct use of `logger.exception` vs `logger.warning`, and lazy `%s` formatting everywhere.
- **`dependency_overrides` is always cleared in a `finally`**, so no test leaks DI state into another.
- **Graceful degradation under a missing system dependency** — a 503 with a clean message rather than a stack trace to the client (Evidence §3).
