# Reject invalid uploads and malformed name lists on `/api/extract`

## Metadata
- **ID**: T-007 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O3, O4 · TRD section(s) §9 (layered input defense), §10; CONSTITUTION §8 (Validate at the edge, Resources are scoped)
- **Depends on**: T-006 · **Wave**: 5
- **Files likely touched**: `app/api/` (upload validation, error codes), `app/domain/` (validation errors), `app/infrastructure/` (encrypted/page-count probe in the rasterizer), `tests/unit/api/`
- **Design**: skip (rules fixed by README §Validation and CONSTITUTION §8; reusable by `/api/ingest` later)

## Goal
Refuse bad input before any expensive work starts, with a specific, actionable error for
each case — so clients learn exactly what was wrong and the service never spends OCR
time or leaks resources on garbage.

## User Story
As an API client integrating the service
I want a precise error when my upload or name list is invalid
So that I can fix the request instead of guessing why it failed

## Functional Description
Checks run in this order; the first failure wins and nothing after it runs:

| # | Condition | Status | `error.code` |
|---|---|---|---|
| 1 | `pdf_file` field missing | 422 | `pdf_file_missing` |
| 2 | Upload has 0 bytes | 400 | `upload_empty` |
| 3 | Upload larger than `max_upload_bytes` (read with a cap — never loads more than limit + 1 byte) | 413 | `upload_too_large` |
| 4 | First bytes are not the PDF signature `%PDF-` (regardless of filename extension or declared content type) | 415 | `upload_not_pdf` |
| 5 | PDF is encrypted / password-protected | 422 | `pdf_encrypted` |
| 6 | PDF cannot be parsed | 422 | `pdf_unreadable` |
| 7 | Page count > `max_pages` | 413 | `pdf_too_many_pages` |
| 8 | `names` not valid JSON, not a list, or an item fails `NamePair` (missing/empty `first_name`/`last_name`) | 422 | `names_invalid` |

- The reusable upload validator lives in the api layer and returns the PDF bytes for the use case; checks 5–7 use the rasterizer port's document probe (no OCR).
- Error bodies follow T-001's shape and include the `request_id`; the message names the limit when one applies (e.g. "max 20 MB") and never echoes file content.
- Each rejection logs `upload_rejected` with the code, size and request id.
- Temp resources: if the upload framework spooled the file to disk, it is closed and removed on every path, accepted or rejected.
- Limits come from `Settings` (defaults: 20 MB, 50 pages).

## Main Flow
1. Client posts a valid PDF and a valid `names` list.
2. Validator runs checks 1–8; all pass.
3. Request proceeds to `ExtractNames` exactly as in T-006.

## Alternative Flows
- **Text file renamed `.pdf`**: Given `notes.pdf` whose content is plain text → `415 upload_not_pdf`.
- **Real PDF named `.txt`**: Given a valid PDF uploaded as `scan.txt` with `content-type: text/plain` → accepted (content decides).
- **Oversized**: Given 21 MB with a 20 MB limit → `413 upload_too_large` without reading the whole stream.
- **Password-protected PDF** → `422 pdf_encrypted`.
- **Bad names item**: Given `names=[{"first_name":"Ana"}]` → `422 names_invalid` naming `last_name`.

## Acceptance Criteria
1. **Content, not extension, decides**
   - Given a plain-text file named `fake.pdf` with content type `application/pdf`, and a real sample PDF named `scan.txt` with content type `text/plain`
   - When each is posted
   - Then the first gets `415 upload_not_pdf` and the second gets `200`
2. **Empty and oversized rejected early**
   - Given a 0-byte upload, and an upload of `max_upload_bytes + 1` bytes
   - When each is posted
   - Then responses are `400 upload_empty` and `413 upload_too_large`, and the OCR port was never called (asserted with a fake)
3. **Unusable PDFs rejected without OCR**
   - Given an encrypted PDF, a truncated PDF, and a PDF with `max_pages + 1` pages (generated in the test)
   - When each is posted
   - Then responses are `422 pdf_encrypted`, `422 pdf_unreadable` and `413 pdf_too_many_pages`, with no OCR call
4. **Name list validated**
   - Given `names` values `"not json"`, `{"first_name":"A"}`, `[{"first_name":"Ana"}]` and `[{"first_name":"","last_name":"Lopez"}]`
   - When each is posted with a valid PDF
   - Then every response is `422 names_invalid` with the error body shape from T-001
5. **No leaked temp files**
   - Given the process temp directory listing before the requests
   - When one accepted and one rejected (oversized) upload are processed
   - Then the temp directory listing afterwards is identical

## Technical Notes *(only if applicable)*
- Validation lives at the edge (driving adapter), not in the use case — CONSTITUTION §8.
- The same validator must be reusable by `POST /api/ingest` in the RAG epic — TRD §9.

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
- [ ] No check inspects `filename` or `content_type` to decide PDF-ness.
- [ ] `max_upload_bytes` and `max_pages` are read from `Settings`; changing them via env changes the 413 boundary in tests.
