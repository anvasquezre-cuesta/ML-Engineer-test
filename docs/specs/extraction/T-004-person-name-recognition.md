# Recognize person names and measure NER against a golden set (spike S1)

## Metadata
- **ID**: T-004 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O1, O4 · TRD section(s) §1 (success criteria), §11, §15 (S1), ADR-004; CONSTITUTION §7
- **Depends on**: T-003 · **Wave**: 3
- **Files likely touched**: `app/application/ports.py`, `app/infrastructure/` (spaCy adapter), `tests/golden/`, `tests/integration/`, `scripts/eval_ner.py`, `docs/trds/document-intelligence-trd.md` (S1 result)
- **Design**: likely-needed (defines the recognizer port contract, the golden-set format and the eval method reused by T-006)

## Goal
Recognize person names — and only person names — in OCR text, and prove with numbers
that the chosen model is good enough on the sample corpus before the endpoint depends on
it. Closes spike S1 with a recorded decision (`en_core_web_sm` kept or `en_core_web_trf`
adopted).

## User Story
As a compliance reviewer
I want the system to report people and not organizations, places or dates
So that my review list is not polluted with entities I don't need to verify

## Functional Description
- Port (application): given a page's text, return the person-entity spans as domain values: `start` and `end` character offsets into that text and the span text. No vendor types cross the port.
- Adapter: spaCy pipeline whose model name comes from `Settings` (default `en_core_web_sm`). Only entities labelled `PERSON` (or `PER` when a Spanish model is configured) are returned; every other label is discarded. The model is loaded once per process (composition root), not per call.
- Leading honorifics captured inside a span (`Dr.`, `Prof.`, `Mr.`, `Mrs.`, `Ms.`) are trimmed from the span offsets and text.
- Golden set (`tests/golden/`): for each of the 5 sample pages, the hand-labelled list of person occurrences (name text as printed, without honorific, and page index), plus labelled negatives that must **not** be reported (at least `Atlas`, `NovaTech Solutions`, `ETH Zurich`, `Stanford University`, `London`, `CTO`).
- Eval script: OCR the sample PDFs (T-003), run the recognizer per page, compare with the golden set (case- and whitespace-insensitive exact name match per page) and print per-document and total precision, recall, false positives and false negatives. Exit code non-zero when precision or recall < 0.90 (TRD §1).
- S1 decision: run the eval with `en_core_web_sm`; if both metrics ≥ 0.90 keep it, otherwise run `en_core_web_trf` and, if it passes, switch the default and record a new ADR. The result (numbers + decision) is written into TRD §15 S1.

## Main Flow
1. Developer runs `uv run python scripts/eval_ner.py`.
2. System OCRs the 5 sample pages and recognizes persons on each.
3. System compares against the golden set and prints precision/recall per document and total.
4. Totals ≥ 0.90 → exit 0; the developer records the S1 result in the TRD.

## Alternative Flows
- **Below threshold with `sm`**: Given precision or recall < 0.90 → script exits 1 listing false positives/negatives; developer runs with `trf` and records the ADR if it passes.
- **Below threshold with both models**: Given neither model reaches 0.90 → the shortfall, the failing cases and a proposal (e.g. post-filter for known non-person patterns) are recorded as an open question in TRD §16 before T-006 proceeds.
- **Model not installed**: Given the configured spaCy model is missing → the adapter raises `InfrastructureError` subclass `NerModelUnavailable` naming the model.

## Acceptance Criteria
1. **Only people are returned**
   - Given the text `"Margaret Thompson met NovaTech Solutions in London on March 15, 2024."`
   - When the recognizer runs (integration, real model)
   - Then exactly one span is returned, `"Margaret Thompson"`, with offsets that slice the original text to that string
2. **Honorifics trimmed**
   - Given the text `"Prepared by: Dr. Olivia Chambers, Research Director"`
   - When the recognizer runs
   - Then the returned span text is `"Olivia Chambers"` and `text[start:end] == "Olivia Chambers"`
3. **Golden set exists and is complete**
   - Given `tests/golden/`
   - When it is loaded
   - Then it covers pages of all 3 sample PDFs (5 pages), contains every person occurrence visible in the scans, and includes the negatives listed above
4. **Eval gate**
   - Given the golden set and the default model
   - When `scripts/eval_ner.py` runs
   - Then it prints precision and recall, and exits 0 only if both are ≥ 0.90 (exit 1 otherwise)
5. **S1 closed**
   - Given the eval has run
   - When the ticket is completed
   - Then TRD §15 S1 contains the measured precision/recall, the date and the model decision (and a new ADR exists if the default model changed)

## Technical Notes *(only if applicable)*
- Model name from `Settings`; no literal model name in the adapter — CONSTITUTION §6.
- Evals are a separate layer from unit tests; never assert exact model output in unit tests — CONSTITUTION §7.
- The `'Atlas'` false positive from the preliminary run is a mandatory golden negative — TRD §15.

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
- [ ] No `spacy` import exists outside `app/infrastructure/`; the port returns only domain types.
- [ ] Running `scripts/eval_ner.py` reproduces the numbers written in TRD §15 S1.
