# Cuesta Partners ML Engineer Take Home Assignment

# Work Log

This document records the actual work performed during the development of the Cuesta Partners ML Engineer Take Home Assignment.

Unlike `DEVELOPMENT_LOG.md`, which describes the planned development approach and architecture, this document is a chronological record of what was actually done, including commands executed, configuration changes, problems encountered, decisions made, and verification results.

---

# 2026-09-18 — Project Initialization

## 1. Created the independent project directory

Created a new project directory:

```
D:\LLM-PROJECTS\OCR-CUESTA PARTNERS\Cuesta Partners\OCR Project\ML-Engineer-test-AV-submission-1
```

The original cloned repository is located separately:

```
D:\LLM-PROJECTS\OCR-CUESTA PARTNERS\Cuesta Partners\OCR Project\ML-Engineer-test
```

The cloned repository is being used only as a reference specification for the assignment.

The implementation is being developed independently in `ML-Engineer-test-AV-submission-1`.

Reason:

* avoid modifying the reference repository;
* build the solution from scratch;
* understand and own the implementation;
* reduce the risk of unintentionally depending on code from the reference repository.

---

## 2. Created the initial project structure

Created the following directories:

```
ML-Engineer-test-AV-submission-1/
├── app/
│   ├── api/
│   ├── models/
│   └── services/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── sample_pdfs/
```

Purpose:

* `app/` contains the application code.
* `app/api/` will contain FastAPI routers.
* `app/models/` will contain application/domain models.
* `app/services/` will contain application and infrastructure services.
* `tests/unit/` will contain isolated unit tests.
* `tests/integration/` will contain component integration tests.
* `tests/e2e/` will contain end-to-end tests.
* `sample_pdfs/` will contain sample documents used for development and testing.

---

## 3. Initialized Git

Initialized Git in the project root:

```
git init
```

The repository was initialized on the `main` branch.

Git is being used from the beginning because the assignment requires a branch and pull request, and the commit history also provides a record of the development process.

---

## 4. Created `.gitignore`

Created a `.gitignore` file containing:

```
.vscode/
req.txt
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
.env.*
*.log
```

The `.vscode/` directory is local development configuration.

`req.txt` is a private/local dependency tracking file and is intentionally excluded from Git.

Python caches, test caches, environment files, and logs are also excluded.

---

## 5. Created the initial Git commit

Created the first commit:

```
a39f4c8 chore: add gitignore
```

The initial commit establishes the Git history before significant implementation work begins.

---

## 6. Created Python package initialization files

Created:

```
app/
├── __init__.py
├── api/
│   └── __init__.py
├── models/
│   └── __init__.py
└── services/
    └── __init__.py
```

These files make the application directories explicit Python packages.

---

# 2026-09-18 — Project Dependency Configuration

## 7. Created `pyproject.toml`

Created the project configuration file with the required runtime and development dependencies.

The project uses Python:

```
>=3.12
```

Main dependencies include:

```
fastapi
uvicorn[standard]
python-multipart
pydantic
pydantic-settings
pytesseract
pymupdf
pillow
spacy
thefuzz
python-Levenshtein
sentence-transformers
chromadb
httpx
```

Development dependencies include:

```
pytest
pytest-asyncio
```

The dependency groups correspond to the main technologies required by the assignment:

* FastAPI for the REST API.
* Uvicorn for serving the application.
* `python-multipart` for multipart file uploads.
* Pydantic for validation and schemas.
* Pydantic Settings for configuration.
* Tesseract through `pytesseract` for OCR.
* PyMuPDF for PDF processing and coordinate handling.
* Pillow for image processing.
* spaCy for person-name NER.
* TheFuzz and python-Levenshtein for fuzzy matching.
* Sentence Transformers for embeddings.
* ChromaDB for the embedded vector store.
* HTTPX for communication with an external LLM endpoint.
* pytest and pytest-asyncio for testing.

Important observation:

`pytesseract` is only the Python wrapper around Tesseract. The actual Tesseract OCR executable still needs to be installed and configured on Windows.

---

# 2026-09-18 — Python Environment

## 8. Reused the existing `agent_env` environment

The existing Conda environment was selected instead of creating another environment.

Environment:

```
agent_env
```

Python version:

```
Python 3.12.13
```

The environment is already being used for other AI/ML learning work, and it was sufficiently clean to reuse.

The project is configured so that `uv` installs project dependencies into this existing environment.

Configured:

```
UV_PROJECT_ENVIRONMENT
```

to point to:

```
C:\Users\User\anaconda3\envs\agent_env
```

Reason:

* avoid creating another virtual environment;
* reduce unnecessary disk usage;
* reuse the existing Python 3.12 environment.

---

# 2026-09-18 — Dependency Installation

## 9. First attempt to run `uv sync`

Executed:

```
uv sync --group dev
```

The first attempt failed with:

```
error: failed to read from file `...\pyproject.toml`: stream did not
contain valid UTF-8
```

Initially, this appeared to be a file-encoding problem.

---

## 10. Investigated the `pyproject.toml` encoding

Checked the beginning of the file as raw bytes:

```
Get-Content .\pyproject.toml -Encoding Byte -TotalCount 20
```

The returned bytes corresponded to normal text beginning with:

```
[project]
```

A further UTF-8 decoding test was performed using PowerShell/.NET.

The complete file could be decoded without an exception.

Therefore, the problem was not simply that the file had been saved as UTF-16 or another obvious incompatible encoding.

---

## 11. Identified and fixed the problematic character

The actual problem was eventually identified as a problematic character in the `description` string inside `pyproject.toml`.

The character was replaced.

After the correction, the dependency installation was retried.

---

## 12. Successfully installed dependencies

Executed again:

```
uv sync --group dev
```

This time the synchronization completed successfully.

This established the project environment and installed the runtime and development dependencies.

---

# 2026-09-18 — Environment Verification

## 13. Verified Python

Executed:

```
python --version
```

Result:

```
Python 3.12.13
```

---

## 14. Verified uv

Executed:

```
uv --version
```

Result:

```
uv 0.11.27
```

---

## 15. Verified major dependencies

Executed an import test covering the main project dependencies.

Result:

```
Core imports OK
```

The following packages successfully imported:

```
fastapi
pydantic
pytesseract
pymupdf
spacy
chromadb
sentence_transformers
```

A warning appeared indicating that the legacy `fitz` API is deprecated and that the modern `pymupdf` import should be used.

Decision:

Use:

```
import pymupdf
```

in the implementation rather than relying on the deprecated `fitz` import.

---

# 2026-09-18 — Initial OCR Architecture Design

## 16. Identified the need for a shared OCR representation

The assignment requires both:

* OCR text for person-name extraction and RAG;
* OCR word-level coordinates for bounding-box localization.

A potential problem would be performing OCR independently for each task.

For example:

```
PDF → OCR → text

PDF → OCR again → coordinates
```

This would unnecessarily repeat an expensive operation and could potentially produce inconsistent results.

Decision:

Perform OCR once and create an internal representation containing both text and word-level coordinate information.

The intended flow is:

```
PDF
 ↓
OCR
 ↓
OCRDocument
 ├── page text
 └── OCR words + coordinates
```

This representation can then be consumed by different downstream components.

---

# 2026-09-18 — OCR Domain Model Design

## 17. Defined the initial `OCRDocument` model

`OCRDocument` represents the complete OCR result for one PDF.

Initial design:

```
OCRDocument
└── pages: list[OCRPage]
```

Purpose:

Keep the complete document organized by page while preserving the relationship between OCR text and its coordinates.

---

## 18. Defined the initial `OCRPage` model

`OCRPage` represents one page of the document.

Initial fields:

```
page_number: int
text: str
words: list[OCRWord]
```

Purpose:

* preserve page boundaries;
* store the complete OCR text for the page;
* retain the individual OCR words required for localization.

The page number will be zero-based to match the assignment API contract.

---

## 19. Defined the initial `OCRWord` model

`OCRWord` represents one OCR-recognized word and its position on the page.

Initial fields:

```
text: str
x: float
y: float
width: float
height: float
```

The coordinates represent the word's bounding rectangle.

The coordinate system must ultimately correspond to the assignment's required PDF coordinate system.

---

# 2026-09-18 — OCR Coordinate Design

## 20. Defined the coordinate requirement

The assignment requires bounding boxes in:

```
PDF coordinate space
```

using:

```
points
```

where:

```
1 point = 1/72 inch
```

The API requires:

```
page_number
x
y
width
height
```

and page numbers must be zero-based.

The OCR implementation therefore needs to account for the transformation between:

```
Rendered image coordinates
```

and:

```
PDF coordinates
```

This will be handled when implementing the OCR service.

---

# 2026-09-18 — Current Status

## Completed

* [x] Created independent project directory.
* [x] Created project structure.
* [x] Initialized Git.
* [x] Created `.gitignore`.
* [x] Created Python package initialization files.
* [x] Created `pyproject.toml`.
* [x] Selected and configured `agent_env`.
* [x] Installed project dependencies.
* [x] Installed development dependencies.
* [x] Verified Python.
* [x] Verified uv.
* [x] Verified major dependency imports.
* [x] Identified the PyMuPDF import convention to use.
* [x] Designed the initial OCR internal representation.
* [x] Defined the initial fields and types for `OCRDocument`.
* [x] Defined the initial fields and types for `OCRPage`.
* [x] Defined the initial fields and types for `OCRWord`.
* [x] Defined the required PDF coordinate representation.

## Current next step

Create:

```
app/models/ocr.py
```

containing the three agreed internal models:

```
OCRDocument
OCRPage
OCRWord
```

After the models are implemented and reviewed, install and verify the Tesseract OCR executable before implementing and testing the OCR service.

---

# Working Method

The work log will continue to be updated throughout development.

For each meaningful step, record:

```
What was done
Why it was done
Commands or implementation details
Problems encountered
How the problem was resolved
Design decisions
Verification/results
```

This document records the actual development process and should remain chronological.

`DEVELOPMENT_LOG.md` remains the higher-level project roadmap and architecture plan.

`DECISIONS.md` will contain the most important technical decisions and their trade-offs.

`DESIGN.md` will describe the final architecture submitted to Cuesta Partners.
