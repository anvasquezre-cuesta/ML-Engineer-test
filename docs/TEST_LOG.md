# Verification and known limitations

This is a concise delivery record. Real provider calls, simulated components and
human review are intentionally distinguished. No result below establishes general
accuracy or production capacity.

## Automated suite

On 2026-11-17, **628 tests passed in 56.34 seconds** in an isolated Linux ARM64
container with the current `app/`, `scripts/`, tests and sample PDFs mounted
read-only. The suite included real Tesseract, spaCy and the pinned embedding model
as well as simulated HTTP and dependency failures. It did not call an external LLM.
The tested runtime image and dependency layers were built using Docker cache.
The test image followed the disposable recipe below; the application's source was
mounted rather than tested as a packaged wheel.

To reproduce with local prerequisites from the README:

```bash
make test
```

Alternatively, after building `document-intelligence-smoke:local`, create a
disposable test image and mount the current sources:

```bash
docker build -t document-intelligence-tests:local - <<'EOF'
FROM document-intelligence-smoke:local
USER root
RUN uv pip install --target /tmp/test-deps 'pytest==9.2.0'
USER appuser
EOF

docker run --rm --network none \
  -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" \
  -v "$PWD/tests:/tests:ro" -v "$PWD/sample_pdfs:/samples:ro" \
  -e PYTHONPATH=/tmp/test-deps:/app -e SAMPLE_PDFS_DIR=/samples \
  -e HF_HUB_OFFLINE=1 --entrypoint python document-intelligence-tests:local \
  -m pytest -q -p no:cacheprovider /tests/unit /tests/integration
```

The suite covers page-local geometry, rotations and crop boxes, fuzzy matching,
resource limits, cancellation, unique ingestion IDs, ledger/vector consistency,
error classification and recovery after simulated dependency failures. Model
provider protocol and retry tests use mocked HTTP; they are not real provider tests.

## Frontend build and geometry

On 2026-11-17, a disposable Node 22 container ran `npm ci --ignore-scripts`,
`npm test` and `npm run build` against the frontend source. All five geometry
tests passed, covering four page rotations and invalid coordinates. The
production build succeeded. `npm audit --omit=dev` found no vulnerabilities;
the full dependency audit reported four high-severity advisories in build-only
dependencies. Vite also warned that a generated JavaScript chunk exceeds 500 kB.

An isolated Compose project and headless Chrome exercised the rebuilt frontend
against real local OCR and NER using an eight-page synthetic scanned PDF. The
returned boxes aligned with the synthetic text in all four rotations, with and
without crop boxes. The browser check also verified repeat extraction, rejection
of a mismatched stored result and an invalid preview token, OCR and final-stage
overlays, and basic extraction with preview disabled and no external LLM. An
earlier run uncovered a PDF.js cleanup error on repeat extraction; the complete
check passed after correcting it. The temporary project's resources were removed.
These automated checks are not a human review or a general accuracy measurement.

After automatic stage loading was added, a further isolated Compose and Chrome
run passed with real OCR/NER on eight synthetic pages: all rotations and crop
variants aligned, OCR/NER/final stages loaded without user credentials, repeat
extraction worked, and basic extraction still worked with preview disabled. The
test project and its volumes were removed. Frontend geometry tests (5) and the
production build also passed in a disposable Node 22 container.

The one-command `make quickstart` was also exercised with a synthetic key in a
temporary, uniquely named **real Compose project**. A test-only override disabled
host ports and added a healthcheck. The key was entered with terminal echo off,
the new `.env` had mode `0600`, Compose built and started the services, the
synthetic Gemini settings reached the app, and `/health` passed. No external LLM
call was made. Only the test project's containers, network, volumes and image tag
were removed. A separate simulated-Compose check confirmed an existing `.env` is
not overwritten on a second run. These checks did not modify the user's services.

## Sample name observations

Real OCR and spaCy were run on all three supplied PDFs. The following are counts
of returned boxes, **not** precision scores. The comparison used the pre-error-
handling image; the name pipeline was not changed by the error-handling work.

| Sample | Pages | Default recovery 0 | Recovery 1–3 |
|---|---:|---:|---:|
| `company_memo.pdf` | 1 | 9 | 9 |
| `meeting_minutes.pdf` | 2 | 22 | 24 |
| `research_report.pdf` | 2 | 25 | 25 |

In `meeting_minutes.pdf`, one of three occurrences of Elizabeth Park appeared
with recovery off; all three appeared with recovery 1. The user visually approved
the level-1 example on both pages; see [MT-002](MANUAL_TEST_LOG.md). This is a
human observation for one example, not a general metric.

An **assistant-only, unapproved** comparison against the page images also found
that `Atlas` in the memo is a project, while `RESEARCH DEPARTMENT - ANNUAL`,
`Breakthrough` and `Forbes` in the research report are not people. The report's
Lucas Zimmermann was not detected even at recovery level 3. The recovery algorithm
can only reuse a full name that NER already found and safely located elsewhere;
it cannot recover a name that never became a seed. These observations need human
annotation and do not justify changing the default to level 1 or filtering all
single-word names. The small English model can both miss people and return
non-persons. Future evaluation should measure per-occurrence precision, recall,
page and bounding-box placement against human-reviewed annotations.

## RAG and failure cases

The real synthetic Gemini evaluation contains all 25 questions, actual responses,
expected and actual pages, and cases that failed or were partial:
[EVALUACION_FUENTES_RAG.md](EVALUACION_FUENTES_RAG.md). A later prompt adjustment
has only been unit-tested, not re-run against Gemini. OpenAI-compatible provider
protocol and retry tests use simulated transport.

Isolated ingestion checks use real HTTP, OCR, embeddings, SQLite and Qdrant,
including repeated documents, empty physical pages, persistence and scoped
cleanup. With `SMOKE_ASK_FAKE=1`, only the answer generator is simulated. The
scripts create their own resources and do not stop existing Compose services:

On 2026-11-17, extraction and ingestion checks passed against the rebuilt
`document-intelligence-delivery-review:20261117-03` image. Generation in the
ingestion check was simulated. An earlier packaged ingestion run exposed a
regression in handling an injected built-in `TimeoutError` during manifest
creation. The error is now classified as a timeout without retrying writes;
unit tests and the full isolated ingestion/cleanup check passed after the fix.

```bash
make smoke-extract
make smoke-rag
```

## Preliminary OCR memory observation

An earlier isolated experiment processed two synthetic raster pages of about
19.8 million pixels each, with two OCR jobs and a 2 GiB container limit. The
reported cgroup peak was **985.3 MiB**. This excluded Uvicorn, Qdrant and loaded
NER/embedding models; it does not calibrate a production limit. Concurrency,
document types, available memory and orientation retries need separate benchmarks.
