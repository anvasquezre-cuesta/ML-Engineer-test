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


# 2026-09-18 — OCR Module Design and Implementation

## 21. Clarified the OCR internal representation

Before implementing the OCR service, the internal representation of OCR results was clarified.

The term **OCR representation** does not refer to a separate module, class, or function. It refers to the Python data structure that our application will use to represent the information produced by OCR.

The application needs two types of OCR information:

1. The text recognized from each page, which will be used by downstream components such as NER and RAG.
2. The individual OCR words together with their positions, which will be used to locate extracted names and produce bounding boxes.

Instead of creating separate OCR operations for these purposes, the application will represent the result of one OCR operation in a structured way.

The conceptual representation is:

```text
PDF
 ↓
OCR
 ↓
OCRDocument
 ├── OCRPage
 │     ├── page text
 │     └── OCRWord + coordinates
 │
 ├── OCRPage
 │     ├── page text
 │     └── OCRWord + coordinates
 │
 └── ...
```

This structure is the **shared OCR representation**.

The decision to use a shared representation is an architectural decision rather than an explicit requirement that OCR must be executed only once. The motivation is to avoid unnecessarily repeating the OCR operation and to keep the text and positional information derived from the same OCR result.

---

## 22. Clarified the role of `OCRDocument`

`OCRDocument` is a **Python class**, not a module and not a function.

The module containing the OCR models is:

```text
app/models/ocr.py
```

The `OCRDocument` class represents the complete OCR result for one PDF document.

Its conceptual structure is:

```text
OCRDocument
└── pages: list[OCRPage]
```

In plain English:

> An `OCRDocument` is the container for all the pages that OCR processed from one PDF.

For example, if a PDF contains three pages:

```text
PDF
│
├── Page 0
├── Page 1
└── Page 2
```

the corresponding OCR representation will contain:

```text
OCRDocument
│
├── OCRPage 0
├── OCRPage 1
└── OCRPage 2
```

The purpose of this class is to keep the complete OCR result organized by page while preserving the relationship between page text and the word-level information associated with that page.

`OCRDocument` does not perform OCR. It only represents the result of OCR.

---

## 23. Clarified the role of `OCRPage`

`OCRPage` is also a **Python class** defined inside the same `app/models/ocr.py` module.

It represents the OCR result for one page of a PDF.

Its initial structure is:

```text
OCRPage
├── page_number: int
├── text: str
└── words: list[OCRWord]
```

In plain English:

> An `OCRPage` is a container that stores everything we need to know about OCR on one particular page.

It contains three pieces of information.

### `page_number`

Identifies which PDF page the OCR result belongs to.

The assignment requires zero-based page numbering, so:

```text
First page  → 0
Second page → 1
Third page  → 2
```

### `text`

Contains the complete OCR text recognized from that page.

For example:

```text
"John Smith attended the meeting."
```

This representation is useful for downstream text-processing components such as NER.

### `words`

Contains a list of `OCRWord` objects.

For example:

```text
[
    OCRWord("John", ...),
    OCRWord("Smith", ...),
    OCRWord("attended", ...),
    OCRWord("the", ...),
    OCRWord("meeting", ...)
]
```

The purpose of keeping individual words is that the bounding-box component needs to know not only what was recognized but also where each word was located.

Therefore:

```text
OCRPage
   │
   ├── text → useful for NER
   │
   └── words → useful for bounding-box localization
```

`OCRPage` does not perform OCR. It represents the OCR result for one page.

---

## 24. Clarified the role of `OCRWord`

`OCRWord` is a **Python class** defined in the same `app/models/ocr.py` module.

It represents one word recognized by OCR together with its position on the page.

Its initial fields are:

```text
OCRWord
├── text: str
├── x: float
├── y: float
├── width: float
└── height: float
```

In plain English:

> An `OCRWord` represents one recognized word and the rectangle that identifies where that word appears on the page.

For example:

```text
OCRWord
├── text   → "John"
├── x      → 100.0
├── y      → 50.0
├── width  → 30.0
└── height → 12.0
```

The `text` field stores the word itself.

The remaining four fields describe its bounding rectangle:

```text
x       → horizontal position
y       → vertical position
width   → width of the rectangle
height  → height of the rectangle
```

The values are represented as `float` because coordinates and dimensions may contain decimal values.

The assignment requires the final bounding-box coordinates to be expressed in PDF coordinate space using points, so the OCR service will be responsible for ensuring that the coordinates stored in these objects use the required coordinate system.

`OCRWord` does not perform OCR and does not perform coordinate conversion. It is simply the internal representation of one OCR-recognized word and its location.

---

## 25. How the three classes connect

The three classes are not three separate modules.

They are three classes inside one module:

```text
app/
└── models/
    └── ocr.py
         ├── OCRWord
         ├── OCRPage
         └── OCRDocument
```

They form a simple hierarchy:

```text
OCRDocument
    │
    │ contains
    ▼
OCRPage
    │
    │ contains
    ▼
OCRWord
```

For a multi-page PDF, the complete structure is:

```text
OCRDocument
│
├── OCRPage 0
│     ├── OCRWord
│     ├── OCRWord
│     └── OCRWord
│
├── OCRPage 1
│     ├── OCRWord
│     ├── OCRWord
│     └── OCRWord
│
└── OCRPage 2
      ├── OCRWord
      ├── OCRWord
      └── OCRWord
```

This hierarchy reflects the natural structure of the input:

```text
PDF
 → pages
   → words
```

The classes therefore provide a simple and explicit internal representation of the OCR result.

---

## 26. Clarified the separation between data and behavior

The OCR models and the OCR processing logic are intentionally separated.

The current module:

```text
app/models/ocr.py
```

defines the **data structures**.

The future module:

```text
app/services/ocr_service.py
```

will contain the **OCR processing behavior**.

Conceptually:

```text
ocr.py
    ↓
defines what an OCR result looks like

ocr_service.py
    ↓
defines how OCR is performed
```

For example:

```text
PDF
 ↓
OCRService
 ↓
OCRDocument
     ↓
     ├── OCRPage
     │      ↓
     │      └── OCRWord
     │
     ├── OCRPage
     │      ↓
     │      └── OCRWord
     │
     └── ...
```

This separation keeps the model classes simple and prevents them from becoming responsible for external operations such as opening PDFs, rendering pages, invoking Tesseract, or converting coordinates.

---

## 27. Clarified the coordinate-system responsibility

The coordinate system is **not another class, module, or function**.

It is a requirement governing what the coordinate values in `OCRWord` mean.

The assignment explicitly requires bounding boxes in:

```text
PDF coordinate space
```

using:

```text
points
```

where:

```text
1 point = 1/72 inch
```

The challenge is that the OCR engine works on a rendered image. Image-based OCR naturally produces coordinates in image/pixel space.

Therefore, conceptually, the OCR process will involve:

```text
PDF
 ↓
render page as image
 ↓
Tesseract OCR
 ↓
image/pixel coordinates
 ↓
coordinate conversion
 ↓
PDF coordinates in points
```

The final `OCRWord` coordinates must represent the required PDF coordinate system.

The coordinate conversion will therefore be implemented as part of the OCR processing logic rather than inside the data model.

This keeps the responsibility of `OCRWord` simple:

> store the recognized word and its final position.

---

## 28. Implemented `app/models/ocr.py`

Created the following module:

```text
app/models/ocr.py
```

The module contains three lightweight Python classes:

```text
OCRWord
OCRPage
OCRDocument
```

The module uses ordinary Python classes rather than `@dataclass`.

The initial implementation was intentionally kept explicit because these classes are simple internal data containers and there is no assignment requirement to use Python dataclasses. Using ordinary classes also makes the initialization behavior straightforward to understand and defend during the technical interview.

The module-level documentation follows Python docstring conventions associated with PEP 257, while the specific `Module`, `Path`, and `Description` format is a project documentation convention.

The implementation is:

```python
"""
Module: app.models.ocr
Path: app/models/ocr.py
Description: Internal data models used to represent OCR results.
"""


class OCRWord:
    """Represent one OCR-recognized word and its position on a page."""

    def __init__(
        self,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class OCRPage:
    """Represent the OCR result for one page of a PDF document."""

    def __init__(
        self,
        page_number: int,
        text: str,
        words: list[OCRWord],
    ) -> None:
        self.page_number = page_number
        self.text = text
        self.words = words


class OCRDocument:
    """Represent the complete OCR result for a PDF document."""

    def __init__(self, pages: list[OCRPage]) -> None:
        self.pages = pages
```

---

## 29. Formatting and linting verification

Ruff was added as a development dependency because it is a development-time code-quality and formatting tool rather than a runtime dependency.

The dependency was added to the development dependency group in `pyproject.toml`.

Ruff was installed through:

```text
uv sync --group dev
```

The installed version was verified:

```text
ruff 0.16.8
```

The OCR module was formatted with:

```text
ruff format app\models\ocr.py
```

Result:

```text
1 file reformatted
```

The module was then checked with:

```text
ruff check app\models\ocr.py
```

Result:

```text
All checks passed!
```

Therefore, the initial OCR model module passed Ruff formatting and linting checks.

---

## 30. Next step — Tesseract OCR

The Python package `pytesseract` is already installed as part of the project's Python dependencies.

However, `pytesseract` is a Python wrapper/interface for the Tesseract OCR engine. The actual Tesseract executable must also be installed and available on the Windows system.

The next implementation step is therefore:

```text
Install Tesseract OCR executable
        ↓
Verify Tesseract from PowerShell
        ↓
Implement app/services/ocr_service.py
        ↓
Run real OCR against the sample PDFs
```

The OCR service will then connect the external OCR engine with the internal models created in `app/models/ocr.py`.
---

## OCR Foundation Checkpoint

### 1. Tesseract OCR installation and verification

Installed Tesseract OCR on the Windows development environment and verified the installation.

Installed executable:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

Verified Tesseract version:

```text
5.5.3.20260724
```

Available languages:

```text
eng
osd
```

The `tesseract` command was not available directly through the PowerShell `PATH`, but the executable worked correctly when invoked through its full path.

### 2. Tesseract configuration decision

The machine-specific Tesseract executable path was deliberately not hardcoded into application source code.

Instead, the application supports an optional configuration value:

```text
APP_TESSERACT_CMD
```

This keeps the application portable across development machines and evaluation environments.

If `APP_TESSERACT_CMD` is not provided, the application can rely on the normal `tesseract` executable lookup through the operating system `PATH`.

### 3. Centralized application configuration

Created:

```text
app/config.py
```

The module uses `pydantic-settings` to centralize application configuration.

Current settings include:

```text
tesseract_cmd
ocr_dpi
```

The OCR DPI has a configurable default value of `300`.

The Tesseract executable path can be supplied through:

```text
APP_TESSERACT_CMD
```

Local development configuration was verified successfully with:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

The local environment variable is not stored in Git.

### 4. OCR internal data model

Created:

```text
app/models/ocr.py
```

The module defines the internal OCR representation:

```text
OCRDocument
    └── OCRPage
          └── OCRWord
```

`OCRWord` represents an OCR-recognized word and its position on a page.

`OCRPage` represents the OCR result for one PDF page.

`OCRDocument` represents the complete OCR result for the PDF.

This internal representation preserves both page text and word-level coordinates so that the same OCR result can later support both NER and bounding-box extraction without running OCR multiple times.

### 5. OCR service skeleton

Created:

```text
app/services/ocr_service.py
```

The module introduces the `OCRService` application service.

The service receives `Settings` through its constructor so that configuration is injected rather than hardcoded.

The service currently exposes:

```text
extract(pdf_path)
```

which will become the main OCR workflow.

The current implementation establishes the service structure but intentionally does not yet perform OCR.

### 6. Code quality verification

Applied Ruff formatting and linting to the new OCR service:

```powershell
ruff format app\services\ocr_service.py
ruff check app\services\ocr_service.py
```

Both checks passed successfully.

### 7. Assignment sample PDFs

Copied the three sample PDFs supplied with the reference assignment repository into the submission repository:

```text
sample_pdfs/
├── company_memo.pdf
├── meeting_minutes.pdf
└── research_report.pdf
```

These files will be used as realistic input documents for development and validation.

The supplied PDFs are not modified.

### 8. Initial PDF processing implementation

Implemented the initial PDF-processing structure inside `OCRService.extract()` using PyMuPDF.

The current workflow:

```text
PDF path
   ↓
PyMuPDF opens PDF
   ↓
Iterate through every page
   ↓
Page number + page object
```

The PDF is opened using a context manager so that the document resource is properly released after processing.

The page iteration uses `enumerate()` so that page numbers are explicitly zero-based, matching the assignment's API requirement.

### 9. Initial execution test

Executed the OCR service against the supplied:

```text
sample_pdfs/company_memo.pdf
```

The service successfully opened the PDF and entered the first page:

```text
Processing page 0
```

Execution then stopped at the intentional:

```python
raise NotImplementedError
```

This confirms that the PDF was successfully located and opened by PyMuPDF and that page iteration has been reached.

The `NotImplementedError` is expected at this stage because actual page rendering and OCR have not yet been implemented.

### 10. Current OCR implementation boundary

At this checkpoint, the OCR workflow is intentionally incomplete.

Implemented:

```text
PDF opening
    ↓
Page iteration
```

Not yet implemented:

```text
PDF page rendering
    ↓
Tesseract OCR
    ↓
Word-level OCR coordinates
    ↓
Pixel-to-PDF coordinate conversion
    ↓
OCRDocument construction
```

The next implementation step is therefore to render each PDF page into an image at the configured DPI. Tesseract will then operate on those rendered page images.

### Git checkpoint

Before continuing with page rendering, the completed work in this checkpoint will be reviewed with:

```powershell
git status
```

The changes will then be staged and committed after confirming that no local-only configuration, cache, or temporary files are included.

Planned commit:

```text
feat: establish OCR service foundation
```
