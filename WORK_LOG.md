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

---

## 11. OCR pipeline — PDF rendering, image conversion, and word-level OCR

After establishing the initial OCR service foundation, the OCR workflow was extended incrementally and validated against the provided sample PDFs.

### 11.1 PDF page iteration

The OCR service now opens the PDF using PyMuPDF and iterates through every page:

```python
with pymupdf.open(pdf_path) as document:
    for page_number, page in enumerate(document):
        ...
```

The PDF is managed through a context manager so the document resource is released after processing.

The page number is obtained from `enumerate(...)` and is therefore naturally 0-based, matching the assignment's API requirement.

### 11.2 PDF page rendering

Each PDF page is rendered independently into a PyMuPDF pixmap.

The rendering resolution is controlled through centralized configuration:

```text
APP_OCR_DPI
```

with a current default of:

```text
300 DPI
```

The implementation calculates the rendering scale relative to the PDF's 72 points-per-inch coordinate system:

```python
scale = self.settings.ocr_dpi / 72
matrix = pymupdf.Matrix(scale, scale)
```

Each page is processed independently rather than rendering the complete document into memory. This keeps the current implementation bounded to the page being processed.

Validation with the provided `meeting_minutes.pdf` confirmed that both pages are rendered:

```text
Page 0: 2550x3300 pixels
Page 1: 2550x3300 pixels
```

### 11.3 In-memory conversion from PyMuPDF to Pillow

The rendered pixmap is converted directly into a Pillow `Image`:

```python
image = Image.frombytes(
    "RGB",
    (pixmap.width, pixmap.height),
    pixmap.samples,
)
```

No temporary PNG/JPEG files are created.

This keeps the OCR pipeline in memory and provides the image representation required by `pytesseract`.

### 11.4 Tesseract OCR with word-level data

Tesseract is executed once per page using:

```python
ocr_data = pytesseract.image_to_data(
    image,
    output_type=pytesseract.Output.DICT,
)
```

`image_to_data()` was selected instead of a plain text OCR call because the assignment requires both:

* recognized text;
* word-level bounding-box coordinates.

Using a single OCR call allows the same OCR result to support both requirements and avoids running Tesseract separately for text extraction and localization.

The returned data contains parallel fields such as:

```text
text
left
top
width
height
conf
block_num
par_num
line_num
```

The current internal model intentionally stores only the information required by the current OCR workflow.

### 11.5 Filtering Tesseract entries

Tesseract's `image_to_data()` output contains more entries than actual words. Some entries represent hierarchical containers or have empty text.

For example, the beginning of the OCR result for page 0 included entries with empty text and confidence `-1`, followed by actual recognized words such as:

```text
BOARD
OF
DIRECTORS
-
MEETING
MINUTES
```

The implementation therefore strips the OCR text and ignores entries whose resulting text is empty.

This produces actual `OCRWord` objects rather than treating every Tesseract entry as a word.

### 11.6 OCRWord construction

Valid OCR entries are converted into the internal `OCRWord` model:

```python
word = OCRWord(
    text=text,
    x=float(ocr_data["left"][i]),
    y=float(ocr_data["top"][i]),
    width=float(ocr_data["width"][i]),
    height=float(ocr_data["height"][i]),
)
```

At this stage, the coordinates stored in `OCRWord` are still **pixel coordinates**.

The `OCRWord` model currently represents:

```text
OCRWord
├── text
├── x
├── y
├── width
└── height
```

OCR confidence is currently not stored because it is not required by the current downstream design.

### 11.7 Validation against sample PDF

The implementation was executed against:

```text
sample_pdfs/meeting_minutes.pdf
```

The resulting diagnostic output was:

```text
Page 0: 198 OCR entries
Page 0: 149 OCR words
Page 1: 178 OCR entries
Page 1: 134 OCR words
PDF rendering completed
```

This confirms:

* the PDF was opened successfully;
* all pages were processed;
* Tesseract OCR executed successfully on every page;
* empty/non-word Tesseract entries were filtered;
* `OCRWord` objects were created for recognized words.

### 11.8 Current OCR implementation boundary

At this checkpoint, the OCR workflow has the following implemented stages:

```text
PDF
 ↓
PyMuPDF document opening
 ↓
Page iteration
 ↓
PDF page rendering
 ↓
PyMuPDF pixmap
 ↓
Pillow image
 ↓
Tesseract image_to_data()
 ↓
Filter empty OCR entries
 ↓
OCRWord objects
```

The following stages are **not yet implemented**:

```text
OCRWord pixel coordinates
        ↓
PDF-point coordinate conversion
        ↓
OCRPage construction
        ↓
OCRDocument construction
        ↓
Return OCRDocument from OCRService
```

This distinction is intentional. The coordinate conversion and document-level models have been designed conceptually but are not recorded as implemented until they have been coded and validated.

### 11.9 Next implementation step

The next step is to construct the `OCRPage` object for each processed PDF page and then construct the final `OCRDocument` containing all pages.

After that, the OCR service will convert the word-level pixel coordinates into the PDF coordinate system required by the assignment and return the completed `OCRDocument`.

### 11.10 Git checkpoint

Before continuing with page/document construction, this OCR pipeline checkpoint should be committed to Git so that the current implementation remains a recoverable, verified state.



## OCR Service — Page and Document Construction + PDF Coordinate Conversion

### Completed

This stage completed the core OCR document representation and coordinate conversion required by the assignment.

The OCR service now processes every page of a PDF, extracts word-level OCR information, converts the word coordinates from image pixels into PDF coordinate space, creates an `OCRPage` object for every processed page, and finally returns one `OCRDocument` containing all processed pages.

The complete flow is:

PDF
↓
PyMuPDF opens the PDF
↓
Iterate through every PDF page
↓
Render each page at the configured OCR DPI
↓
Convert the rendered page into a Pillow image
↓
Run Tesseract `image_to_data()`
↓
Filter empty OCR entries
↓
Convert pixel coordinates to PDF points
↓
Create `OCRWord` objects
↓
Construct `OCRPage` for the current PDF page
↓
Append `OCRPage` to the document page collection
↓
Construct `OCRDocument`
↓
Return the complete `OCRDocument`

### 1. Constructing an `OCRPage` for Each Processed PDF Page

The OCR service iterates through the complete PDF using PyMuPDF:

```text
for page_number, page in enumerate(document):
```

The important architectural detail is that the construction of the `OCRPage` occurs **inside this outer page-processing loop**.

This guarantees that every PDF page produces its own `OCRPage`.

An earlier indentation problem caused the `OCRPage` construction to occur outside the page loop. Tesseract was processing both pages correctly, but only the final page was being added to the `OCRDocument`. The implementation was corrected so that the page object is created and appended during each iteration.

The intended structure is:

```text
for page_number, page in enumerate(document):
    process current page
    create OCRWord objects
    create OCRPage for current page
    append OCRPage to pages
```

This is important because the final document must preserve the page structure of the original PDF.

### 2. Creating the Page-Level OCR Text

After the OCR words for the current page have been created, the service constructs the page-level text:

```text
text=" ".join(word.text for word in words)
```

This takes the recognized words in their OCR order and joins them with spaces.

The result is stored in the `OCRPage.text` attribute.

This gives downstream components two representations of the same page:

* `OCRPage.text` — convenient page-level text for NER and other text-processing operations.
* `OCRPage.words` — word-level information including coordinates for later localization.

This separation is important because NER does not need to understand OCR coordinates, while the later bounding-box logic will need the individual words and their positions.

### 3. Constructing the `OCRPage`

The current page is converted into an `OCRPage` with:

```text
ocr_page = OCRPage(
    page_number=page_number,
    text=" ".join(word.text for word in words),
    words=words,
)
```

Each field has a specific responsibility.

`page_number=page_number`

Preserves the original zero-based PDF page index required by the assignment.

`text=" ".join(word.text for word in words)`

Stores the complete OCR text for the page.

`words=words`

Stores all of the recognized words together with their converted PDF-coordinate bounding boxes.

After the object is created, it is added to the document-level page collection:

```text
pages.append(ocr_page)
```

This operation must remain inside the page-processing loop.

### 4. Constructing the Final `OCRDocument`

The service starts with an empty collection:

```text
pages: list[OCRPage] = []
```

Each processed PDF page contributes one `OCRPage` to this collection.

After the outer page loop has completed, the service returns:

```text
return OCRDocument(pages=pages)
```

The resulting structure is therefore:

```text
OCRDocument
├── OCRPage 0
│   ├── page_number
│   ├── text
│   └── words
│       ├── OCRWord
│       ├── OCRWord
│       └── ...
├── OCRPage 1
│   ├── page_number
│   ├── text
│   └── words
│       ├── OCRWord
│       ├── OCRWord
│       └── ...
└── ...
```

This provides the complete structured OCR representation of the PDF.

### 5. Converting Tesseract Pixel Coordinates to PDF Coordinates

Tesseract reports word-level bounding boxes relative to the rendered image, so its coordinates are expressed in pixels.

The assignment requires bounding boxes in PDF coordinate space using points, where:

```text
72 points = 1 inch
```

The OCR service therefore converts the Tesseract coordinates before constructing each `OCRWord`.

The conversion is:

```text
PDF points = image pixels × (72 / OCR DPI)
```

The implementation calculates the conversion factor using the configured OCR DPI:

```text
scale_to_pdf = 72 / self.settings.ocr_dpi
```

The current default OCR DPI is 300, so:

```text
scale_to_pdf = 72 / 300
```

Therefore:

```text
1 image pixel = 0.24 PDF points
```

The conversion is applied independently to:

* `x`
* `y`
* `width`
* `height`

### 6. Constructing the Converted `OCRWord`

The relevant implementation is:

```text
word = OCRWord(
    text=text,
    x=float(ocr_data["left"][i]) * scale_to_pdf,
    y=float(ocr_data["top"][i]) * scale_to_pdf,
    width=float(ocr_data["width"][i]) * scale_to_pdf,
    height=float(ocr_data["height"][i]) * scale_to_pdf,
)
```

The purpose of each line is:

`text=text`

Stores the OCR-recognized word.

`x=float(ocr_data["left"][i]) * scale_to_pdf`

Takes Tesseract's left position in pixels and converts it into PDF points.

`y=float(ocr_data["top"][i]) * scale_to_pdf`

Takes Tesseract's top position in pixels and converts it into PDF points.

`width=float(ocr_data["width"][i]) * scale_to_pdf`

Converts the OCR bounding-box width from pixels into PDF points.

`height=float(ocr_data["height"][i]) * scale_to_pdf`

Converts the OCR bounding-box height from pixels into PDF points.

The conversion happens before the `OCRWord` object is created. Consequently, the internal OCR representation returned by the service already contains coordinates in the coordinate system required by the assignment.

### 7. Why the Conversion Is Performed in the OCR Service

Tesseract operates on raster images and naturally returns pixel coordinates.

The rest of the application should not need to know that implementation detail.

The OCR service therefore acts as the boundary between the OCR engine and the application's internal representation:

```text
Tesseract
   ↓
pixel coordinates
   ↓
OCRService
   ↓
PDF-coordinate OCRWord
```

This keeps coordinate-system conversion in one place.

Later components can work directly with PDF coordinates without repeating the conversion or knowing how Tesseract represents locations.

### 8. Complete OCR Processing Flow at This Stage

The OCR service now performs the following operations:

```text
PDF
 ↓
Open with PyMuPDF
 ↓
Iterate through every page
 ↓
Render current page at configured DPI
 ↓
Convert PyMuPDF pixmap to Pillow image
 ↓
Run Tesseract image_to_data()
 ↓
Iterate through OCR entries
 ↓
Remove empty entries
 ↓
Convert pixel coordinates to PDF points
 ↓
Create OCRWord
 ↓
Create OCRPage
 ↓
Append OCRPage to pages
 ↓
Repeat for every PDF page
 ↓
Create OCRDocument
 ↓
Return OCRDocument
```

The service therefore ends this stage with a complete structured OCR document rather than raw OCR output.

### 9. Validation Using `meeting_minutes.pdf`

The implementation was tested against:

```text
sample_pdfs\meeting_minutes.pdf
```

The PDF contains two pages.

The OCR service produced:

```text
Page 0: 198 OCR entries
Page 0: 149 OCR words
Page 1: 178 OCR entries
Page 1: 134 OCR words
```

The resulting document contained:

```text
Pages: 2
```

The page-level word counts were:

```text
Page 0 words: 149
Page 1 words: 134
```

This confirmed that both PDF pages were processed and that each page was correctly represented in the final `OCRDocument`.

### 10. Coordinate Conversion Validation

The first OCR word was:

```text
BOARD
```

Its converted bounding box was:

```text
x = 48.48
y = 48.48
width = 32.88
height = 7.20
```

The source PDF page dimensions were independently checked using PyMuPDF:

```text
PDF page size: 612.00 × 792.00 points
```

The resulting right and bottom edges of the OCR bounding box were:

```text
Right edge: 81.36
Bottom edge: 55.68
```

The bounding box therefore lies within the PDF page boundaries.

This confirmed that the coordinates are now expressed in PDF points rather than the original 300-DPI image pixels.

### 11. Final Functional Verification

After the coordinate conversion was implemented, the complete OCR test was executed again.

The final result was:

```text
Page 0: 198 OCR entries
Page 0: 149 OCR words
Page 1: 178 OCR entries
Page 1: 134 OCR words
Pages: 2
Page 0 words: 149
Page 1 words: 134
First word: BOARD
Bounding box: x=48.48, y=48.48, width=32.88, height=7.20
```

This confirmed that the coordinate conversion did not break the existing OCR page-processing or document-construction behavior.

### 12. Code Quality Verification

The standard project workflow was executed after the implementation.

Formatting:

```text
ruff format app
```

Result:

```text
7 files left unchanged
```

Linting:

```text
ruff check app
```

Result:

```text
All checks passed!
```

The functional OCR test was then executed again after formatting and linting and produced the expected result.

### 13. Current Architecture Boundary

The OCR service currently owns:

```text
PDF → OCRDocument
```

The OCR document contains:

```text
OCRDocument
    ↓
OCRPage
    ↓
OCRPage.text
OCRPage.words
    ↓
OCRWord
    ↓
PDF-coordinate bounding box
```

The next component will consume the page-level OCR text and identify person names.

The responsibilities will remain separated:

```text
OCR Service
PDF → OCRDocument

NER Service
OCR text → detected person names

Bounding-Box Logic
detected person name + OCR words → PDF bounding box

Fuzzy Matching
extracted person name → provided name list
```

The OCR service therefore does not perform NER or fuzzy matching. Its responsibility ends after producing the complete, structured, coordinate-normalized OCR document.

### 14. Current Status

The OCR service foundation is complete for this stage.

Completed:

* PDF opening with PyMuPDF
* Iteration through every PDF page
* Configurable OCR DPI
* PDF page rendering
* In-memory Pillow image conversion
* Tesseract OCR
* Word-level OCR extraction
* Empty OCR entry filtering
* Pixel-to-PDF coordinate conversion
* `OCRWord` construction
* `OCRPage` construction for every processed page
* `OCRDocument` construction containing all pages
* Page-level OCR text construction
* PDF-coordinate boundary verification
* Ruff formatting
* Ruff linting
* Functional OCR verification

The next development stage is the **NER layer**, which will use the structured `OCRDocument` produced here to identify person names in the OCR text.
---
# Next Development Stage — NER Layer

## 1. Objective

With the OCR layer validated, the next development stage was to add **Named Entity Recognition (NER)**.

The objective of this stage is to use the structured `OCRDocument` already produced by `OCRService` and identify **person names only** from the OCR text.

The intended flow is:

```text
OCRDocument
    ↓
OCRPage.text
    ↓
spaCy NER
    ↓
PERSON entities
    ↓
NEREntity
```

At this stage, bounding boxes are **not** handled by the NER service. Bounding-box localization will be implemented separately in Block 2.

---

## 2. Technology Selection — spaCy

spaCy was selected for the NER layer because the assignment explicitly calls for named entity recognition and spaCy provides a pretrained NER model suitable for identifying entities such as `PERSON`, `ORG`, `DATE`, `LOC`, etc.

The English model used is:

```text
en_core_web_sm
```

The model was initially checked with:

```python
spacy.util.is_package("en_core_web_sm")
```

The result was:

```text
False
```

The model was then installed and verified again. The verification subsequently returned:

```text
True
```

This confirmed that the model was available in the project environment.

---

## 3. NER Internal Model

A new internal model was created:

`app/models/ner.py`

```python
"""
Module: app.models.ner
Path: app/models/ner.py
Description: Internal data models used to represent NER results.
"""


class NEREntity:
    """Represent one entity detected by named entity recognition."""

    def __init__(
        self,
        text: str,
        label: str,
        page_number: int,
    ) -> None:
        self.text = text
        self.label = label
        self.page_number = page_number
```

The model intentionally contains only:

* `text`
* `label`
* `page_number`

Bounding-box information was intentionally left out because that is a different responsibility and will be addressed in **Block 2 — Bounding Boxes / Name Localization**.

The separation is:

```text
NEREntity
    ↓
What entity was detected and on which page?

Bounding-box service
    ↓
Where exactly is that entity located on the page?
```

---

# 4. Initial NER Service

A new service was created:

`app/services/ner_service.py`

The first implementation was intentionally simple. It received a spaCy model through dependency injection, processed each OCR page separately, and retained only entities whose label was `PERSON`.

The initial version was:

```python
"""
Module: app.services.ner_service
Path: app/services/ner_service.py
Description: Service responsible for named entity recognition.
"""

import spacy

from app.models.ner import NEREntity
from app.models.ocr import OCRDocument


class NERService:
    """Identify named entities in OCR text."""

    def __init__(self, nlp: spacy.Language) -> None:
        self.nlp = nlp

        def extract(self, document: OCRDocument) -> list[NEREntity]:
            """Identify person entities in an OCR document."""

            entities: list[NEREntity] = []

            for page in document.pages:
                doc = self.nlp(page.text)

                for entity in doc.ents:
                    if entity.label_ != "PERSON":
                        continue

                    ner_entity = NEREntity(
                        text=entity.text,
                        label=entity.label_,
                        page_number=page.page_number,
                    )

                    entities.append(ner_entity)

            return entities
```

---

# 5. First Implementation Problem — Incorrect Method Indentation

The first implementation contained an indentation error.

The `extract()` method was accidentally defined inside `__init__()`:

```python
def __init__(...):
    self.nlp = nlp

    def extract(...):
        ...
```

instead of being a normal method of the `NERService` class:

```python
def __init__(...):
    self.nlp = nlp

def extract(...):
    ...
```

When the service was executed, Python raised:

```text
AttributeError: 'NERService' object has no attribute 'extract'
```

### Resolution

The indentation was corrected so that `extract()` became a proper instance method.

This was caught immediately through focused validation before continuing with the implementation.

---

# 6. First Successful NER Run

After correcting the indentation, the service was run against:

```text
sample_pdfs/meeting_minutes.pdf
```

The initial result was:

```text
PERSON entities: 26
```

At first glance this looked promising, but the actual entity list revealed problems.

Among the detected `PERSON` entities were:

```text
DIRECTORS - MEETING MINUTES Date
Richard Hernandez
- Thomas Muller
Aisha Patel
Kevin O'Brien
- Jennifer Liu
Absent
Carlos Mendoza
...
Approved
Richard Hernandez
```

The actual person names were being detected, but spaCy was also producing several false positives and formatting artifacts.

This led to the next step: **diagnosing exactly what spaCy was returning rather than immediately modifying the implementation.**

---

# 7. NER Diagnostic — Inspecting Exact Entity Spans

A diagnostic was created to inspect:

* page number
* exact entity text
* entity label
* character start position
* character end position

The diagnostic showed, for example:

```text
Page 0: text='DIRECTORS - MEETING MINUTES Date', label='PERSON', start=9, end=41
Page 0: text='Richard Hernandez', label='PERSON', start=141, end=158
Page 0: text='- Thomas Muller', label='PERSON', start=224, end=239
Page 0: text='Aisha Patel', label='PERSON', start=272, end=283
Page 0: text="Kevin O'Brien", label='PERSON', start=308, end=321
Page 0: text='- Jennifer Liu', label='PERSON', start=339, end=353
Page 0: text='Absent', label='PERSON', start=365, end=371
Page 0: text='Carlos Mendoza', label='PERSON', start=375, end=389
```

And on page 1:

```text
Page 1: text='Thomas Muller', label='PERSON', start=21, end=34
Page 1: text='Yuki Tanaka', label='PERSON', start=131, end=142
Page 1: text='Alexander Popov', label='PERSON', start=224, end=239
...
Page 1: text='Approved', label='PERSON', start=886, end=894
Page 1: text='Richard Hernandez', label='PERSON', start=899, end=916
```

This diagnostic was important because it established that the false positives were actually coming from the spaCy NER output.

The OCR text itself had already been inspected and was sufficiently clean.

Therefore, there was no reason to redesign the OCR layer.

---

# 8. Problems Identified

Three main issues were identified.

### Problem 1 — False positive containing multiple non-name words

spaCy classified:

```text
DIRECTORS - MEETING MINUTES Date
```

as:

```text
PERSON
```

This clearly does not represent a person name.

### Problem 2 — Single-word false positives

spaCy classified:

```text
Absent
```

and:

```text
Approved
```

as:

```text
PERSON
```

These are not person names in the context of the document.

### Problem 3 — Leading punctuation

Some valid person names were returned with list punctuation:

```text
- Thomas Muller
- Jennifer Liu
```

The actual desired entity text is:

```text
Thomas Muller
Jennifer Liu
```

---

# 9. Decision — Do Not Add Name-Specific Exceptions

An important design decision was made at this point.

The false positives were **not** removed using rules such as:

```python
if entity.text == "Absent":
    continue
```

or:

```python
if entity.text == "Approved":
    continue
```

That would make the implementation dependent on the exact sample document.

Instead, a small generic normalization and validation step was introduced.

The reasoning was:

```text
spaCy
    ↓
candidate PERSON entity
    ↓
generic normalization
    ↓
generic structural validation
    ↓
accepted person name
```

This makes the post-processing rule applicable to similar OCR/NER artifacts rather than only to the current PDF.

---

# 10. Final NER Service

The final version of:

`app/services/ner_service.py`

is:

```python
"""
Module: app.services.ner_service
Path: app/services/ner_service.py
Description: Service responsible for named entity recognition.
"""

import re

import spacy

from app.models.ner import NEREntity
from app.models.ocr import OCRDocument


class NERService:
    """Identify named entities in OCR text."""

    def __init__(self, nlp: spacy.Language) -> None:
        self.nlp = nlp

    def _normalize_person_name(self, text: str) -> str | None:
        """Normalize and validate a person-name entity."""

        normalized = text.strip(" \t\r\n-–—:;,.")
        tokens = normalized.split()

        if len(tokens) < 2:
            return None

        if not all(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token) for token in tokens):
            return None

        return normalized

    def extract(self, document: OCRDocument) -> list[NEREntity]:
        """Identify person entities in an OCR document."""

        entities: list[NEREntity] = []

        for page in document.pages:
            doc = self.nlp(page.text)

            for entity in doc.ents:
                if entity.label_ != "PERSON":
                    continue

                person_name = self._normalize_person_name(entity.text)

                if person_name is None:
                    continue

                ner_entity = NEREntity(
                    text=person_name,
                    label=entity.label_,
                    page_number=page.page_number,
                )

                entities.append(ner_entity)

        return entities
```

---

# 11. Explanation of the Final NER Implementation

The service now has two clear responsibilities.

## `extract()`

`extract()` controls the NER workflow.

For each OCR page:

```text
OCR page text
    ↓
spaCy
    ↓
all detected entities
    ↓
keep only PERSON
    ↓
normalize and validate
    ↓
create NEREntity
```

The important filtering step is:

```python
if entity.label_ != "PERSON":
    continue
```

spaCy recognizes many entity types, but the assignment specifically requires person names.

Therefore, entities such as:

```text
DATE
TIME
ORG
LOC
GPE
CARDINAL
PRODUCT
PERCENT
```

are ignored.

---

## `_normalize_person_name()`

The helper performs two generic operations.

### First: remove surrounding punctuation

```python
normalized = text.strip(" \t\r\n-–—:;,.")
```

For example:

```text
"- Thomas Muller"
```

becomes:

```text
"Thomas Muller"
```

The rule is generic and does not contain any knowledge of the particular person's name.

### Second: require at least two tokens

```python
tokens = normalized.split()

if len(tokens) < 2:
    return None
```

This eliminates the observed single-word false positives:

```text
Absent
Approved
```

while retaining the expected first-name/last-name structures:

```text
Richard Hernandez
Elizabeth Park
Thomas Muller
Aisha Patel
Carlos Mendoza
Yuki Tanaka
Alexander Popov
Catherine Dubois
```

### Third: verify that each token contains alphabetic characters

```python
if not all(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token) for token in tokens):
    return None
```

This prevents obviously malformed candidate spans from being accepted.

The character range also includes common Latin accented characters, which is useful for multilingual names without introducing a language-specific name dictionary.

---

# 12. Final Validation

After the changes, the same validation was run against:

```text
sample_pdfs/meeting_minutes.pdf
```

The final result was:

```text
PERSON entities: 23
```

The resulting entities were:

```text
Page 0: 'Richard Hernandez' [PERSON]
Page 0: 'Thomas Muller' [PERSON]
Page 0: 'Aisha Patel' [PERSON]
Page 0: "Kevin O'Brien" [PERSON]
Page 0: 'Jennifer Liu' [PERSON]
Page 0: 'Carlos Mendoza' [PERSON]
Page 0: 'Richard Hernandez' [PERSON]
Page 0: 'Jennifer Liu' [PERSON]
Page 0: 'Elizabeth Park' [PERSON]
Page 0: 'Thomas Muller' [PERSON]
Page 0: 'Elizabeth Park' [PERSON]
Page 0: 'Aisha Patel' [PERSON]
Page 0: "Kevin O'Brien" [PERSON]
Page 1: 'Thomas Muller' [PERSON]
Page 1: 'Yuki Tanaka' [PERSON]
Page 1: 'Alexander Popov' [PERSON]
Page 1: 'Richard Hernandez' [PERSON]
Page 1: 'Catherine Dubois' [PERSON]
Page 1: 'Aisha Patel' [PERSON]
Page 1: "Kevin O'Brien" [PERSON]
Page 1: 'Richard Hernandez' [PERSON]
Page 1: 'Jennifer Liu' [PERSON]
Page 1: 'Richard Hernandez' [PERSON]
```

The problematic entities identified during the first run were no longer present:

```text
DIRECTORS - MEETING MINUTES Date
Absent
Approved
```

The leading punctuation was also removed:

```text
- Thomas Muller
- Jennifer Liu
```

resulting in:

```text
Thomas Muller
Jennifer Liu
```

---

# 13. Why We Consider the NER Layer Complete

The NER layer now successfully performs its intended responsibility:

```text
OCRDocument
    ↓
page-level OCR text
    ↓
spaCy NER
    ↓
PERSON filtering
    ↓
generic normalization/validation
    ↓
NEREntity[]
```

It also preserves the page number, which will be required later when producing the final extraction response.

Most importantly, the implementation does **not** perform OCR again.

The OCR layer already produced the structured representation required for subsequent stages:

```text
OCRDocument
├── page text
└── OCR words + coordinates
```

NER consumes the page text while Block 2 will consume the same OCR word information to resolve the physical location of each detected name.

---

# 14. Validation and Code Quality

After the final NER implementation was completed, the application code was formatted and linted using:

```powershell
ruff format app
ruff check app
```

The checks passed successfully.

The NER implementation was therefore validated both functionally against the sample PDF and statically through the project's formatting/linting checks.

---

# 15. Block 1 Completion

With the NER layer validated, **Block 1 — OCR + NER is complete**.

The current internal pipeline is:

```text
PDF
 ↓
OCRService
 ↓
OCRDocument
 ├── page text
 └── OCR words + PDF-space coordinates
 ↓
NERService
 ↓
PERSON entities
 ├── text
 ├── label
 └── page_number
```

The next development stage is:

**Block 2 — Bounding Boxes / Name Localization**

The key problem to solve there is how to connect:

```text
spaCy entity
    ↓
character offsets in page text
    ↓
corresponding OCR words
    ↓
word-level coordinates
    ↓
combined bounding box
```

Development is intentionally paused here at the end of Block 1.


## Block 2 — Bounding Boxes: Preserve NER Character Spans

### Objective

Preserve the position of each detected person name within the original OCR page text so that the NER result can later be connected to the physical OCR words and their coordinates.

### Implementation

Updated `app/models/ner.py` so that `NEREntity` now stores:

* `text`
* `label`
* `page_number`
* `start`
* `end`

The `start` and `end` values represent **character positions in the original OCR text**.

Updated `app/services/ner_service.py` to populate these values using spaCy's character offsets:

* `entity.start_char`
* `entity.end_char`

The implementation initially used `entity.start` and `entity.end`, which represent token positions rather than character positions. Functional validation immediately exposed this issue, so the implementation was corrected before proceeding.

### Validation

The OCR → NER pipeline was executed again against `sample_pdfs/meeting_minutes.pdf`.

Results:

* 2 pages processed.
* 23 valid `PERSON` entities detected.
* Character spans correctly identify the corresponding locations in the OCR text.
* Most entities reproduce the normalized entity text exactly when the span is applied to the original OCR text.

Two entities contain a leading `-` in the original span:

* `- Thomas Muller`
* `- Jennifer Liu`

This is expected because the NER character span refers to the original OCR text, while the NER normalization removes surrounding punctuation from the exposed entity name. This distinction is intentional and will not affect bounding-box calculation.

### Important Bounding-Box Principle

The character span is used to connect the recognized name with the OCR words that physically appear on the page.

For a multi-word name such as `Richard Hernandez`, the space between the words is part of the textual name span and therefore matters when identifying the complete name.

However, the space does not have its own physical bounding box. The final bounding box will be created by combining the physical OCR bounding boxes of the words that make up the name.

Conceptually:

`Richard` + `Hernandez` → one combined bounding box

The bounding box therefore covers both words and the space between them, without treating the space as a separate OCR object.

### Code Quality

Ran:

`ruff format app`

Result: all files unchanged.

Ran:

`ruff check app`

Result: all checks passed.

### Milestone Status

**Block 2 — Step 1 complete.**

The NER stage now preserves enough positional information to connect detected names with their OCR words. The next step is to implement and validate the mapping from the NER character span to the corresponding OCR words and then combine their coordinates into a single PDF-space bounding box.

## Block 2 — Step 2: Map NER spans to OCR words

### Objective

Map each detected `NEREntity` to the specific `OCRWord` objects that correspond to its character span in the original OCR page text.

The key design decision is to use the character positions already provided by NER (`start` and `end`) rather than searching for the entity's text again in the OCR text. This is important when the same person name appears multiple times on the same page. Each NER occurrence has its own character span, so the system can identify the correct OCR words without ambiguity.

### Implementation

Created `app/services/bbox_service.py` with a focused `BoundingBoxService`.

The service reconstructs the character range of each OCR word from the way `OCRPage.text` was originally constructed:

```python
text = " ".join(word.text for word in words)
```

For each OCR word, its character start and end positions are reconstructed while iterating through `page.words`. The service then checks whether the OCR word's character range overlaps the NER entity's `[start, end)` span.

The service returns the matching `OCRWord` objects. It does not calculate the final bounding box yet.

### Important design principle

The system does not search for the detected name string inside the OCR text.

For example, if `Richard Hernandez` appears three times on a page, NER provides three different character spans. Each span is independently mapped to its corresponding OCR words and therefore to its own physical coordinates.

This avoids incorrectly selecting the first occurrence of a repeated name.

### Validation

The implementation was validated against `sample_pdfs/meeting_minutes.pdf`.

Results:

* All 23 valid PERSON entities identified by NER were successfully mapped to OCR words.
* Multi-word names correctly mapped to their component OCR words.
* Repeated names such as `Richard Hernandez` produced different coordinates for different occurrences.
* OCR coordinates were confirmed to be available in PDF coordinate space.
* OCR punctuation artifacts were observed in some matches, such as `Hernandez,`, `Patel,`, and a leading `-`. These will be handled generically when constructing the final bounding box rather than through sample-specific exclusions.

### Milestone status

**Block 2 — Step 2 complete.**

The next step is to construct the final PDF-space bounding box from the relevant OCR words while ensuring punctuation artifacts do not unnecessarily enlarge the detected name's box.

## Block 2 — Step 3: Construct the PDF-Space Bounding Box

### Objective

Construct a single bounding box from the OCR words that correspond to a detected person name.

At this stage, the `BoundingBoxService` already knows which `OCRWord` objects belong to the NER entity. The next responsibility is to combine their individual PDF-space coordinates into one rectangle representing the complete detected name.

### Implementation

Added `create_bounding_box()` to `app/services/bbox_service.py`.

The method first removes OCR tokens that contain only punctuation. This prevents formatting artifacts such as a leading `-` from unnecessarily expanding the bounding box.

```python
relevant_words = [
    word for word in words if any(character.isalnum() for character in word.text)
]
```

This uses a generic rule rather than document-specific exclusions:

* `"-"` → excluded
* `","` → excluded
* `"Thomas"` → included
* `"Muller,"` → included

A word containing punctuation together with actual name characters is retained because its OCR bounding box represents the physical location of the name text.

The final rectangle is calculated from the outermost coordinates of the relevant OCR words:

```python
left = min(word.x for word in relevant_words)
top = min(word.y for word in relevant_words)
right = max(word.x + word.width for word in relevant_words)
bottom = max(word.y + word.height for word in relevant_words)
```

The result is converted to the required `(x, y, width, height)` representation:

```python
return (
    left,
    top,
    right - left,
    bottom - top,
)
```

If no usable OCR words remain after filtering, the method returns `None` rather than producing an invalid bounding box.

### Validation

The implementation was tested using the actual OCR coordinates from the `Thomas Muller` example.

The punctuation-only `-` was correctly excluded.

The resulting bounding box was:

```text
(60.0, 199.68, 65.28, 8.639999999999986)
```

The expected dimensions are effectively:

* **x:** 60.00
* **y:** 199.68
* **width:** 65.28
* **height:** 8.64

The small floating-point representation difference in the returned height is normal Python floating-point behavior and does not affect the bounding box calculation.

### Code Quality Validation

After the functional validation:

```text
ruff format app
ruff check app
```

Both commands completed successfully:

```text
9 files left unchanged
All checks passed!
```

### Design Principle

The bounding box is calculated entirely from OCR coordinates that were already converted to **PDF coordinate space in points** during the OCR stage.

No additional image processing or pixel-to-PDF conversion is required at this step.

### Milestone Status

**Block 2 — Step 3 complete.**

## Block 2 — Step 4.1 Part A: Create the Internal Extraction Result Model

### Objective

Introduce an internal result model for the extraction workflow.

The extraction workflow needs to return a meaningful representation of a detected person name together with its location, but it should not return the FastAPI/Pydantic response models directly.

This establishes a clear separation between the internal application layer and the external API contract.

### Implementation

Created:

```text
app/models/extraction.py
```

The module contains the `ExtractedNameResult` class:

```python
class ExtractedNameResult:
    """Represent an extracted person name and its PDF-space location."""

    def __init__(
        self,
        name: str,
        page_number: int,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self.name = name
        self.page_number = page_number
        self.x = x
        self.y = y
        self.width = width
        self.height = height
```

The model represents the information required by the API layer:

* `name` — the detected person name.
* `page_number` — the 0-based PDF page number.
* `x` — left coordinate in PDF points.
* `y` — top coordinate in PDF points.
* `width` — bounding-box width in PDF points.
* `height` — bounding-box height in PDF points.

### Architectural Boundary

The internal model is intentionally separate from the API-facing Pydantic models defined in `app/models/schemas.py`.

The intended flow is:

```text
Internal processing
        ↓
ExtractedNameResult
        ↓
API mapping
        ↓
ExtractedName + BoundingBox
```

This prevents the extraction workflow from becoming coupled to FastAPI or to the exact HTTP response schema.

The workflow can therefore be tested independently of HTTP, while the API layer remains responsible for constructing the externally defined response objects.

### Scope of This Step

This step only introduced the internal result model.

No changes were made yet to:

* the FastAPI extraction router;
* the `/api/extract` endpoint;
* the extraction workflow;
* fuzzy matching;
* the existing API response schemas.

These responsibilities will be connected progressively in subsequent steps.

### Code Quality Validation

After creating the module:

```text
ruff format app
ruff check app
```

The results were:

```text
1 file reformatted, 10 files left unchanged
All checks passed!
```

### Design Principle

The model follows the project's agreed separation of concerns:

> **Application workflow models represent internal processing results; API models represent the external contract.**

This keeps the workflow independent from the HTTP layer while still giving the API layer all the information needed to construct the required `ExtractionResponse`.

### Milestone Status

**Block 2 — Step 4.1 Part A complete.**

## Block 2 — Bounding Boxes: Extraction Workflow

### Part D — Connect NER entities to OCR pages and bounding-box matching

**Objective**

Extend the extraction workflow so that each `NEREntity` is connected to the correct `OCRPage` and passed to the `BoundingBoxService` for word-level matching.

**Implementation**

Updated:

`app/services/extraction_service.py`

The `ExtractionService.extract()` workflow now:

1. Calls `NERService.extract(document)` to obtain detected person entities.
2. Iterates through each `NEREntity`.
3. Uses the entity's `page_number` to identify the corresponding `OCRPage`.
4. Passes the page and entity to `BoundingBoxService.find_matching_words()`.

The workflow now has the following structure:

```text
OCRDocument
    ↓
NERService
    ↓
NEREntity[]
    ↓
For each entity
    ↓
Correct OCRPage
    ↓
BoundingBoxService
    ↓
Matching OCRWord[]
```

At this stage, the matching words are intentionally not yet converted into a final bounding box or `ExtractedNameResult`. Those operations will be added in the next incremental step.

### Design Principles

* **Separation of concerns:** `ExtractionService` coordinates the extraction use case without implementing OCR, NER, or geometric calculations itself.
* **Single responsibility:** `BoundingBoxService` remains responsible for mapping entities to OCR words.
* **Dependency injection:** `ExtractionService` receives its NER and bounding-box dependencies through its constructor.
* **Incremental implementation:** The workflow is being constructed in small functional pieces rather than introducing the complete method at once.

### Validation

Ran:

```text
ruff format app
```

Result:

```text
1 file reformatted, 11 files left unchanged
```

Then:

```text
ruff check app
```

Result:

```text
All checks passed!
```

The temporary unused-variable warnings were resolved by not assigning intermediate values until those values are actually consumed by the next workflow stage.

### Milestone Status

**Block 2 — Part D: COMPLETE**

The extraction workflow can now obtain NER entities, identify their source pages, and invoke the bounding-box word-matching logic.

## Block 2 — Bounding Boxes: Extraction Workflow

### Part E — Complete the internal extraction workflow

**Objective**

Complete the `ExtractionService` workflow so that detected person entities are transformed into internal extraction results containing their names and PDF-space bounding boxes.

**Implementation**

Updated:

`app/services/extraction_service.py`

The workflow now:

1. Calls `NERService.extract()` to obtain `NEREntity` objects.
2. Uses each entity's `page_number` to retrieve the corresponding `OCRPage`.
3. Calls `BoundingBoxService.find_matching_words()` to identify the OCR words belonging to the entity.
4. Calls `BoundingBoxService.create_bounding_box()` to calculate the combined PDF-space rectangle.
5. Handles the case where no usable bounding box can be created by skipping that entity.
6. Unpacks the bounding-box coordinates.
7. Creates an `ExtractedNameResult` containing:

   * person name;
   * page number;
   * x coordinate;
   * y coordinate;
   * width;
   * height.
8. Appends the result to the workflow's result collection.
9. Returns the complete list of extraction results.

The resulting internal workflow is:

```text
OCRDocument
    ↓
NERService
    ↓
NEREntity[]
    ↓
OCRPage
    ↓
matching OCRWord[]
    ↓
PDF-space bounding box
    ↓
ExtractedNameResult
    ↓
list[ExtractedNameResult]
```

### Design Decisions

The `ExtractionService` acts as the application-level orchestrator. It does not perform OCR, NER, or geometric calculations itself.

The responsibilities remain separated:

```text
OCRService
    → Extract OCR text and word coordinates

NERService
    → Identify PERSON entities

BoundingBoxService
    → Map entities to OCR words and calculate geometry

ExtractionService
    → Coordinate the complete extraction use case
```

The workflow returns the internal `ExtractedNameResult` model rather than the API's Pydantic response models. This preserves the boundary between application logic and the HTTP/API layer.

The `None` check for the bounding box provides an explicit failure path when an entity cannot be mapped to usable OCR words. The workflow skips that invalid result instead of creating an incomplete response object.

### Code Quality Validation

Ran:

```text id="o1x2m4"
ruff format app
```

Result:

```text id="e7q4n1"
All files formatted successfully.
```

Then:

```text id="t9c5r2"
ruff check app
```

Result:

```text id="b3k8v6"
All checks passed!
```

No linting errors remain.

### Milestone Status

**Block 2 — Part E: COMPLETE**

The internal extraction workflow is now implemented end-to-end:

**OCR → NER → page lookup → OCR-word matching → PDF-space bounding box → internal extraction result.**

The next milestone is validation of this workflow with realistic OCR/NER data before connecting it to the FastAPI endpoint.

## Block 2 — Bounding Boxes: Extraction Workflow

### Unit Test — Validate the extraction workflow

**Objective**

Add a focused unit test for `ExtractionService` to verify that a detected person entity can be mapped to OCR words and converted into the expected PDF-space bounding box.

The test intentionally isolates application logic from heavyweight external dependencies such as Tesseract and spaCy.

### Implementation

Created:

`tests/unit/test_extraction_service.py`

The test uses:

* a deterministic `FakeNERService`;
* manually constructed `OCRDocument`, `OCRPage`, and `OCRWord` objects;
* the real `BoundingBoxService`;
* the real `ExtractionService`.

The test therefore exercises this application path:

```text
FakeNERService
      ↓
ExtractionService
      ↓
BoundingBoxService
      ↓
ExtractedNameResult
```

The test verifies:

* exactly one extraction result is produced;
* the extracted name is correct;
* the page number is correct;
* the bounding-box coordinates are correct;
* the calculated width and height are correct.

The expected geometry is derived from two OCR words:

```text
Richard     x=60, width=35
Hernandez   x=98, width=55
```

Therefore the combined bounding box extends from `x=60` to `x=153`, producing a width of `93`.

### Testing Strategy

This is intentionally a **unit test**, rather than an integration or E2E test.

Heavy dependencies are replaced with deterministic test data so that the test:

* runs quickly;
* is deterministic;
* does not depend on Tesseract installation;
* does not depend on the spaCy model;
* tests our application logic rather than third-party library behavior.

Integration and E2E tests will be added later at the appropriate architectural boundaries.

### Code Quality Validation

Ran:

```text
ruff format tests/Unit/test_extraction_service.py
```

and:

```text
ruff check tests/Unit/test_extraction_service.py
```

Both completed successfully.

### Test Validation

Ran:

```text
pytest tests/Unit/test_extraction_service.py -v
```

Result:

```text
1 passed in 4.32s
```

The extraction workflow therefore passes its first focused unit test.

### Design Principles Demonstrated

* **Dependency inversion:** `ExtractionService` receives its NER and bounding-box dependencies instead of creating them internally.
* **Testability:** the NER dependency can be replaced with a deterministic fake.
* **Separation of concerns:** the test validates orchestration and geometry without testing Tesseract or spaCy internals.
* **Focused testing:** the test protects a non-trivial piece of application logic rather than merely checking that a method executes.

### Milestone Status

**Block 2 — Extraction workflow unit test: COMPLETE**

The internal extraction workflow has now been validated both against the real sample PDF and through a deterministic unit test.

## Block 2 — Bounding Boxes

### Unit Test — Entity character span to OCR-word mapping

**Objective**

Add a focused unit test for `BoundingBoxService.find_matching_words()` to verify that an NER entity's character span is correctly mapped to the OCR words representing that specific occurrence.

### Implementation

Created:

`tests/unit/test_bbox_service.py`

The test constructs a deterministic `OCRPage` containing:

```text
Richard Hernandez was present
```

and four OCR words with known character positions and PDF-space coordinates.

A `NEREntity` is created with:

```text
name: Richard Hernandez
start: 0
end: 17
```

The test then calls:

```python
service.find_matching_words(page, entity)
```

and verifies that only:

```text
Richard
Hernandez
```

are returned.

The words `was` and `present` must not be included.

### Design Decision Protected by the Test

The test protects the decision to use the NER entity's **character span** as the occurrence identifier.

The implementation does not search for the name using a generic string operation such as:

```python
page.text.find(entity.text)
```

This is important because a document can contain the same person's name multiple times. A simple string search could identify the wrong occurrence.

The intended mapping is:

```text
NEREntity
(start, end)
      ↓
OCR word character ranges
      ↓
Correct OCRWord objects
```

### Testing Strategy

The test is a true unit test:

* no PDF is opened;
* Tesseract is not executed;
* spaCy is not executed;
* no external service is used;
* deterministic OCR objects are supplied directly.

This keeps the test fast and makes the behavior under test explicit.

### Code Quality Validation

Ran:

```text
ruff check tests/unit/test_bbox_service.py
```

Result:

```text
All checks passed!
```

### Test Validation

Ran:

```text
pytest tests/unit/test_bbox_service.py -v
```

Result:

```text
1 passed in 0.04s
```

### Milestone Status

**Block 2 — Character-span mapping test: COMPLETE**

The entity-to-OCR-word mapping is now protected by a deterministic unit test.
---
## Block 2 — Bounding Boxes

### Unit Test — OCR-word geometry to PDF-space bounding box

**Objective**

Extend the bounding-box unit tests to verify that multiple OCR words are correctly combined into a single PDF-space bounding box.

### Implementation

Updated:

`tests/unit/test_bbox_service.py`

The module now contains two focused unit tests:

1. `test_find_matching_words_uses_entity_character_span()`

   * Verifies that an NER character span identifies the correct OCR words.
   * Confirms that unrelated words are excluded.

2. `test_create_bounding_box_combines_word_coordinates()`

   * Verifies that the coordinates of the matching OCR words are combined into one bounding rectangle.

For the geometry test, the two words have these coordinates:

```text id="u2kd9f"
Richard
x = 60
width = 35

Hernandez
x = 98
width = 55
```

The expected combined rectangle is:

```text id="xv5g8k"
x      = 60
y      = 100
width  = 93
height = 8
```

This independently verifies the bounding-box calculation performed by `BoundingBoxService`.

### Testing Strategy

The geometry test uses deterministic `OCRWord` objects and does not involve:

* PDF files;
* Tesseract;
* spaCy;
* FastAPI;
* external services.

This keeps the test fast and focused on application-owned geometry logic.

Together, the two tests now protect:

```text id="y8nv5x"
NER character span
       ↓
correct OCR words
       ↓
PDF-space bounding box
```

### Code Quality Validation

Ran:

```text id="w6hx8m"
ruff check tests/unit/test_bbox_service.py
```

Result:

```text id="x3gq2v"
All checks passed!
```

### Test Validation

Ran:

```text id="n4p7zs"
pytest tests/unit/test_bbox_service.py -v
```

Result:

```text id="a6m1yc"
2 passed in 0.04s
```

Both unit tests passed successfully.

### Design Principles Demonstrated

* **Focused tests:** each test protects one important piece of application behavior.
* **Determinism:** no heavyweight ML or OCR dependencies are required.
* **Separation of concerns:** matching logic and geometry logic are tested independently.
* **Regression protection:** future changes to bounding-box logic will be checked against explicit expected behavior.

### Milestone Status

**Block 2 — Bounding-box unit tests: COMPLETE**

The two critical bounding-box operations are now covered by deterministic unit tests.

## Block 2 — Bounding Boxes

### Dependency Injection — Application Service Providers

**Objective**

Establish a clean dependency-injection boundary between the FastAPI API layer and the application services before implementing the `/api/extract` endpoint.

**Implementation**

Created:

`app/dependencies.py`

The module provides cached dependency factories for:

* application `Settings`;
* `OCRService`;
* `ExtractionService`.

The extraction dependency constructs the required components:

```text id="p2x8rc"
NER model
    ↓
NERService
    ↓
BoundingBoxService
    ↓
ExtractionService
```

The API layer will later obtain these services through FastAPI dependency injection instead of constructing them directly inside endpoint functions.

### Caching Decision

`@lru_cache` is used on dependency-provider functions where the resulting object should be reused within the application process.

This is particularly important for the spaCy NER model. Loading the model for every HTTP request would introduce unnecessary initialization overhead.

The intended lifecycle is:

```text id="b3o6j1"
First dependency request
        ↓
Create service / load model
        ↓
Cache instance
        ↓
Subsequent requests reuse instance
```

`lru_cache` is not being treated as a general-purpose decorator for every function or method. It is being used specifically for reusable application-level dependencies.

### Architectural Boundary

The design separates responsibilities:

```text id="v8a1xq"
FastAPI router
    ↓
Dependency injection
    ↓
Application services
    ↓
Infrastructure / ML components
```

This prevents the HTTP layer from becoming responsible for model loading and service construction.

It also improves testability because the application service can continue to receive explicitly supplied dependencies, as already demonstrated by the `FakeNERService` unit test.

### Code Quality Validation

Ran:

```text id="t3n6v8"
ruff format app/dependencies.py
```

and:

```text id="q5m2s9"
ruff check app/dependencies.py
```

Result:

```text id="h7c4pa"
All checks passed!
```

### Milestone Status

**Dependency-injection foundation: COMPLETE**

The service construction boundary is now established. The next step is to use these dependencies from the FastAPI extraction endpoint while keeping the router thin.

## Block 2 — Step 4.2: Implement the `POST /api/extract` Router

### Objective

Connect the existing OCR and extraction workflow to the FastAPI HTTP layer while keeping the router thin and preserving separation of concerns.

### Implementation

Created `app/api/extract.py` as the HTTP entry point for `POST /api/extract`.

The router is responsible for:

* Receiving the scanned PDF as a multipart upload.
* Receiving the `names` field as a JSON string.
* Validating the supplied names against the existing `NamePair` schema.
* Validating the basic PDF filename requirement.
* Creating a temporary PDF file for the OCR service.
* Delegating OCR processing to `OCRService`.
* Delegating person-name extraction and bounding-box calculation to `ExtractionService`.
* Mapping internal `ExtractedNameResult` objects into the public `ExtractionResponse` API schema.
* Cleaning up the temporary PDF file in a `finally` block.

The router does **not** perform OCR, NER, coordinate calculations, or fuzzy matching itself.

### Dependency Injection

The endpoint receives `OCRService` and `ExtractionService` through FastAPI's dependency-injection mechanism.

Conceptually:

```text
HTTP request
    ↓
FastAPI router
    ↓
OCRService
    ↓
ExtractionService
    ↓
ExtractionResponse
```

This keeps HTTP concerns separate from application logic and allows the services to be replaced with test doubles during testing.

### Validation

Ruff initially reported `B008` for FastAPI's normal use of `File(...)`, `Form(...)`, and `Depends(...)` in endpoint parameters.

The Ruff configuration was adjusted with a targeted per-file ignore:

```toml
[tool.ruff.lint.per-file-ignores]
"app/api/*.py" = ["B008"]
```

This keeps the rule active throughout the rest of the application while allowing the standard FastAPI dependency/declaration pattern in API routers.

Validation completed successfully:

```text
ruff check app/api/extract.py
All checks passed!

ruff check app
All checks passed!
```

### Design Principles

This step reinforces:

* **Separation of concerns** — the router handles HTTP concerns; services handle application logic.
* **Dependency injection** — services are supplied to the endpoint rather than constructed inside the endpoint.
* **Thin API layer** — business logic remains outside the router.
* **Resource management** — temporary files are explicitly cleaned up.
* **Targeted lint configuration** — Ruff is not globally weakened to accommodate a framework-specific pattern.

### Milestone Status

**Block 2 — Bounding Boxes / Name Localization: In progress**

Completed within Block 2:

1. NER character spans
2. OCR-word/entity span mapping
3. Bounding-box geometry
4. Extraction workflow
5. Extraction workflow unit tests
6. Bounding-box unit tests
7. FastAPI dependency providers
8. `POST /api/extract` router implementation

The next step is to connect the router to the main FastAPI application and verify the HTTP route before proceeding to fuzzy matching.

## Block 2 — Step 4.3: Register the Extraction Router in the FastAPI Application

### Objective

Create the FastAPI application entry point and connect the completed extraction router to the application.

### Implementation

Created:

`app/main.py`

The module now:

* Creates the FastAPI application.
* Registers the extraction router under the `/api` prefix.
* Exposes the extraction endpoint as:

```text
POST /api/extract
```

* Provides the required health endpoint:

```text
GET /health
```

The RAG router was intentionally **not registered yet**, because the RAG implementation belongs to Block 4 and does not yet exist in the submission project.

### Architecture

The current HTTP structure is:

```text
FastAPI application
       │
       ├── GET /health
       │
       └── /api
             │
             └── POST /api/extract
                    │
                    ▼
              Extraction Router
                    │
                    ▼
              Application Services
```

This keeps `main.py` focused on application assembly rather than business logic.

### Validation

Formatting and linting completed successfully:

```text
ruff format app/main.py
→ All checks passed

ruff check app/main.py
→ All checks passed

ruff check app
→ All checks passed
```

### Design Principles

This step reinforces:

* **Separation of concerns** — `main.py` assembles the application; it does not implement extraction logic.
* **Thin routers** — HTTP behavior remains in the API layer.
* **Explicit application composition** — routers are registered centrally.
* **Incremental architecture** — RAG is not registered until its implementation exists.

### Milestone Status

**Block 2 — Bounding Boxes / Name Localization: nearly complete**

The extraction workflow now has a complete path from the FastAPI application through the extraction router to the OCR/NER/bounding-box services.

The next validation step is to **run the FastAPI application and verify the registered routes**, before moving to fuzzy matching.

## Block 2 — Step 4.4: Validate FastAPI Route Registration

### Objective

Verify that the FastAPI application starts successfully and that the required HTTP routes are correctly registered.

### Validation

The application was started with:

```text id="q1m2ds"
uv run uvicorn app.main:app --reload
```

Uvicorn reported:

```text id="p8h7ak"
Application startup complete.
```

The locally generated OpenAPI specification was then queried through:

```text id="e5r6ty"
Invoke-RestMethod http://127.0.0.1:8000/openapi.json
```

The returned specification contained the expected routes:

```text id="j3k4lm"
/api/extract
/health
```

This confirms that:

* `app.main` can be imported successfully.
* The FastAPI application can be instantiated.
* The extraction router is correctly registered.
* The `/api` prefix is applied correctly.
* The health endpoint is registered.
* FastAPI can generate the application's OpenAPI schema.

No external LLM service was involved in this validation. The OpenAPI specification is generated locally by FastAPI and is independent of OpenAI credits or the eventual Ollama/Llama 3 configuration.

### Architecture Status

The HTTP routing layer is now connected to the extraction workflow:

```text
FastAPI
    │
    ├── GET /health
    │
    └── POST /api/extract
            │
            ▼
       Extraction Router
            │
            ├── OCRService
            │
            └── ExtractionService
                    ├── NERService
                    └── BoundingBoxService
```

### Milestone Status

**Block 2 — Bounding Boxes / Name Localization: nearly complete**

The extraction functionality is now connected from the application entry point through the API layer to the OCR, NER, and bounding-box services.

The remaining extraction work includes integrating the provided-name fuzzy matching required by the assignment and then validating the complete endpoint behavior.

## Block 2 — Step 4.5: Validate the Extraction Endpoint End-to-End

### Objective

Validate the complete HTTP extraction path using a real scanned PDF and confirm that the FastAPI endpoint successfully connects the HTTP layer to the OCR, NER, and bounding-box workflow.

### Integration Test

The endpoint was called with the real sample document:

```text
sample_pdfs/meeting_minutes.pdf
```

using:

```text
POST /api/extract
```

The request successfully passed through the following pipeline:

```text
HTTP multipart request
        ↓
PDF upload
        ↓
Temporary PDF file
        ↓
OCRService
        ↓
OCRDocument
        ↓
ExtractionService
        ↓
NERService
        ↓
BoundingBoxService
        ↓
ExtractionResponse
```

The endpoint returned **23 extracted person-name results**, covering both pages of the document.

Each result contained:

* the extracted person name;
* the zero-based page number;
* the PDF-space `x` and `y` coordinates;
* the PDF-space width and height.

The returned coordinates were consistent with the PDF coordinate-space representation established earlier in Block 2.

### Validation Observation

A request containing:

```text
names=[]
```

was successfully accepted and returned the complete extraction response.

A non-empty JSON list transmitted through the PowerShell `curl.exe` command did not reach the application in the expected JSON representation. Because the empty list was accepted and the complete extraction pipeline executed successfully, this was identified as a **PowerShell/curl multipart quoting issue rather than an application extraction failure**.

No application code was changed to compensate for the shell-specific behavior.

### Response Validation

The endpoint returned:

```text
fuzzy_matches: []
```

This is currently expected because fuzzy matching has not yet been implemented.

The successful response demonstrates that the extraction functionality is independent of the future fuzzy-matching component.

### Engineering Validation

The extraction endpoint was validated through the actual running FastAPI application rather than only through direct service calls.

The test therefore exercised:

* FastAPI route registration;
* multipart file handling;
* request validation;
* temporary-file creation and cleanup;
* OCR service integration;
* NER service integration;
* bounding-box calculation;
* response-model serialization.

### Milestone Status

**Block 2 — Bounding Boxes / Name Localization: COMPLETE**

The extraction path is now connected from the HTTP API through the application workflow to OCR, NER, and PDF-space bounding-box generation.

The next milestone is:

**Block 3 — Fuzzy Name Matching**
