# `POST /api/extract` end to end

## Metadata
- **ID**: T-006 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O1, O2, O3, O4 · TRD section(s) §1, §2, §3, §10, §11; CONSTITUTION §2.1, §4.5, §7, §9
- **Depends on**: T-002, T-004, T-005 · **Wave**: 4
- **Files likely touched**: `app/application/` (`ExtractNames` use case), `app/api/` (extract router, DTO mapping, DI provider), `app/main.py` (wiring), `tests/unit/application/`, `tests/unit/api/`, `tests/e2e/`, `scripts/eval_boxes.py`
- **Design**: skip (contract fixed by `schemas.py`; orchestration fixed by TRD §2)

## Goal
Deliver the feature the PRD asks for: upload a scanned PDF and a list of names, get back
every person name with its page and box in PDF points plus the fuzzy matches — assembled
from T-002…T-005 behind a thin router, and proven on the real sample PDFs.

## User Story
As a compliance reviewer (or the system that serves them)
I want to upload a scanned PDF with the names I'm checking and receive every person mention with its exact location and the matches against my list
So that I can verify each mention on the page and cross-check it against other records

## Functional Description
- Request: `multipart/form-data` with `pdf_file` (file) and `names` (JSON string: list of `{"first_name","last_name"}`). Response: `ExtractionResponse` exactly as in `schemas.py`.
- `ExtractNames` use case (application), constructed with its ports and settings by the composition root: OCR all pages (T-003) → for each page build the page text (T-005) → recognize persons on that text (T-004) → align spans to occurrences (T-005) → match the unique extracted names against the requested names (T-002) → return a domain result.
- Router (driving adapter): reads the upload, parses `names` into `NamePair`s, calls the use case, maps the domain result to `ExtractionResponse`: one `ExtractedName` per occurrence with `bounding_box` = `{page_number, x, y, width, height}` in points; `fuzzy_matches` from T-002. The router contains no business rules.
- Ordering: `extracted_names` ordered by page, then top-to-bottom, then left-to-right; `fuzzy_matches` as defined in T-002.
- `names` may be an empty list `[]` → extraction still runs and `fuzzy_matches` is `[]`.
- Minimal input handling in this ticket: an unreadable PDF surfaces T-003's `PdfUnreadable` as 422 and a `names` value that is not valid JSON of the expected shape as 422 through the T-001 error mapping. The full validation set (magic bytes, size, page count, encrypted, empty) is T-007.
- CPU-bound work runs in a sync (`def`) route so the event loop is not blocked — TRD §8.
- Logging: one `extraction_completed` event with document SHA-256 prefix, page count, occurrence count, unique-name count, match count and per-stage durations (ocr, ner, align, match). No names or text in logs.
- Box self-check eval (`scripts/eval_boxes.py`): for every returned box on the sample PDFs, render that region at high DPI, OCR it, and fuzzy-compare the result with the reported name; report the pass rate (TRD §1 requires 100 %) and occurrence recall against the T-004 golden set (≥ 0.95).

## Main Flow
1. Client posts `company_memo.pdf` with `names=[{"first_name":"Margaret","last_name":"Thompson"}]`.
2. Router validates the form fields and calls `ExtractNames`.
3. Use case OCRs, recognizes, aligns and matches.
4. Router returns `200` with every person occurrence (each with page 0 and a box in points) and one fuzzy match for Margaret Thompson with score ≥ 0.90.

## Alternative Flows
- **No persons in the document**: Given a PDF whose text has no PERSON entities → `200` with `extracted_names: []` and `fuzzy_matches: []`.
- **Requested names not found**: Given names absent from the document → `200` with all extracted names and `fuzzy_matches: []`.
- **OCR engine unavailable**: Given Tesseract is missing → `503` with `error.code = "ocr_unavailable"` and the `request_id`.
- **Malformed `names`**: Given `names="not json"` → `422` with a specific error code.

## Acceptance Criteria
1. **Contract and coordinates on real samples** *(e2e)*
   - Given each PDF in `sample_pdfs/` posted with `names=[]`
   - When `POST /api/extract` is called
   - Then the response is `200`, validates against `ExtractionResponse`, every `page_number` is within the document's page range (both pages of the 2-page PDFs appear), and every box lies within 612×792
2. **Repeated names produce one entry per mention** *(e2e)*
   - Given `meeting_minutes.pdf`
   - When it is extracted
   - Then the number of `Richard Hernandez` entries equals the golden-set count of its occurrences, each with a distinct box
3. **Fuzzy matches returned** *(e2e)*
   - Given `company_memo.pdf` with `names=[{"first_name":"Margaret","last_name":"Thompson"},{"first_name":"María","last_name":"García"},{"first_name":"Ana","last_name":"Lopez"}]`
   - When it is extracted
   - Then `fuzzy_matches` contains Margaret Thompson and Maria Garcia (score ≥ 0.90) and nothing for Ana Lopez
4. **Use case testable without HTTP**
   - Given `ExtractNames` built with fake ports (scripted pages, spans) and no FastAPI import in the test
   - When it runs on a 2-page fake document
   - Then it returns the expected occurrences for both pages and calls OCR for page 0
5. **Box self-check eval passes**
   - Given the sample PDFs and the golden set
   - When `scripts/eval_boxes.py` runs
   - Then 100 % of returned boxes re-OCR to their name with score ≥ 0.90, occurrence recall is ≥ 0.95, and the script exits 0

## Technical Notes *(only if applicable)*
- `app/models/schemas.py` unchanged; mapping functions live in `app/api/` — ADR-012.
- Adapters and the use case are built once in the lifespan and injected through a dependency provider — CONSTITUTION §4.5.
- Response box origin is top-left in points; documented in the route's OpenAPI description — TRD ADR-003.

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
- [ ] The extract router module has no `if`/loop implementing a business rule (only parsing, the use-case call and DTO mapping).
- [ ] A captured `extraction_completed` log record contains no extracted name string.
