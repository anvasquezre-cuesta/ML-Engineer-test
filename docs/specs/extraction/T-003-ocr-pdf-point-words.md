# OCR every page into words with boxes in PDF points

## Metadata
- **ID**: T-003 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O1, O3, O4 · TRD section(s) §2 (Extract flow), §10, ADR-002, ADR-003; CONSTITUTION §4, §8
- **Depends on**: T-001 · **Wave**: 2
- **Files likely touched**: `app/domain/` (document/page/word value objects, px→pt geometry), `app/application/ports.py`, `app/infrastructure/` (PyMuPDF rasterizer, Tesseract OCR adapter), `tests/unit/domain/`, `tests/integration/`, `tests/fakes/`
- **Design**: likely-needed (defines the `PdfRasterizer`/`OcrEngine` port contracts and the `Word`/`Page` domain types every later ticket consumes)

## Goal
Turn a scanned PDF into, for every page, the ordered list of recognized words with their
bounding boxes already expressed in PDF points (72/inch, top-left origin). This is the
location data that makes every extracted name auditable.

## User Story
As a compliance reviewer
I want every word the system reads to carry its exact position in the original PDF's coordinate space
So that any name later reported can be found on the page where the system says it is

## Functional Description
- Domain types: a `BoundingBox` in PDF points (`x`, `y`, `width`, `height`, all ≥ 0, top-left origin, y down); a `Word` (text, box, confidence 0..100, line identifier); a `Page` (0-based index, width/height in points, ordered words).
- Domain geometry: `points = pixels × 72 / dpi`, applied to x, y, width and height. This conversion happens **once**, in the OCR adapter; domain `Word`s are always in points.
- Ports (application): rasterize a PDF (bytes) into page images with their DPI and page size in points; OCR a page image into words with pixel boxes and line ids. Port signatures use domain types only.
- Adapters: PyMuPDF renders **every** page (index 0..n-1) at the configured DPI; Tesseract (`image_to_data`) with configured languages returns word text, box, confidence and block/paragraph/line ids. Empty-text tokens and tokens with confidence below the configured floor are dropped. Words keep Tesseract reading order.
- Page rotation: boxes are reported for the page as displayed (PyMuPDF's rotation-aware page rect), so a rotated page's boxes still overlay correctly.
- Resource handling: the PDF document and page images are opened in scoped contexts; nothing is written to disk, or if a temp file is unavoidable it is deleted by the same scope on success and failure.
- Errors: a PDF that cannot be opened → `DomainError` subclass (e.g. `PdfUnreadable`); Tesseract binary missing or crashing → `InfrastructureError` subclass (`OcrUnavailable`). A page with no recognized words yields a `Page` with an empty word list and a log event `ocr_page_empty` with the page index — it is never skipped silently.
- Log per document: `ocr_completed` with page count, total words and duration per page; never the text.

## Main Flow
1. Caller provides the bytes of `sample_pdfs/meeting_minutes.pdf`.
2. Rasterizer renders pages 0 and 1 at the configured DPI.
3. OCR adapter recognizes words on each page image and converts their boxes to points.
4. Result: 2 `Page`s (index 0 and 1), each 612×792 pt, each with its ordered words in points.

## Alternative Flows
- **Corrupt or non-openable PDF**: Given bytes that PyMuPDF cannot open → `PdfUnreadable` is raised; no OCR call is made.
- **Tesseract not installed**: Given the binary is absent → `OcrUnavailable` is raised with a message naming the missing binary; no partial result is returned.
- **Blank page**: Given a page with no text → that `Page` is returned with zero words and `ocr_page_empty` is logged.

## Acceptance Criteria
1. **Every page, including the first**
   - Given a fake rasterizer producing 3 page images
   - When the OCR step runs
   - Then the result has pages with indexes `[0, 1, 2]` in order and the OCR engine was invoked exactly 3 times
2. **Pixel boxes become PDF points**
   - Given a word box `(x=300, y=150, w=600, h=60)` px at 300 DPI
   - When it is converted
   - Then the box is `(72.0, 36.0, 144.0, 14.4)` pt; and at 150 DPI the same pixel box yields `(144.0, 72.0, 288.0, 28.8)`
3. **Real samples land inside the page** *(integration)*
   - Given each PDF in `sample_pdfs/`
   - When it is OCR'd with default settings
   - Then the page counts are 1, 2, 2; every word box lies within `0 ≤ x, x+width ≤ 612` and `0 ≤ y, y+height ≤ 792`; and page 0 of `company_memo.pdf` contains the words `Margaret` and `Thompson`
4. **Resolution independence** *(integration)*
   - Given `company_memo.pdf` OCR'd at 150 DPI and at 300 DPI
   - When the boxes of the word `Thompson` (first occurrence) are compared
   - Then their x and y differ by at most 2 pt
5. **Meaningful failures, no leaks**
   - Given non-PDF bytes, and separately a missing Tesseract binary (faked at the adapter boundary)
   - When OCR is requested
   - Then `PdfUnreadable` and `OcrUnavailable` are raised respectively, and the process's temp directory contains no new files afterwards

## Technical Notes *(only if applicable)*
- DPI, OCR languages and confidence floor come from `Settings` — CONSTITUTION §6.
- Integration tests need the Tesseract binary; they are marked `integration` so the fast suite runs without it — TRD §11.
- PyMuPDF is AGPL; keep it isolated behind the rasterizer port so it can be swapped for pypdfium2 — TRD ADR-003.

## Agent Validation
Checklist for a reviewer agent to determine the ticket was implemented correctly:

- [ ] Every acceptance criterion passes.
- [ ] No contradictions between expected behavior and the implementation.
- [ ] No open functional decisions remain.
- [ ] Main and alternative flows fully covered.
- [ ] No semantic ambiguity.
- [ ] The functionality is automatically testable.
- [ ] The implementation stays consistent with the other tickets.
- [ ] Documentation remains in sync with implemented behavior.
- [ ] No hidden functional dependencies.
- [ ] Behavior can be validated by another agent without human intervention.
- [ ] No `fitz`, `pytesseract` or `PIL` import exists outside `app/infrastructure/` (import-linter passes).
- [ ] The px→pt conversion exists in exactly one domain function and is called only from the OCR adapter.
