# Locate every occurrence of a recognized name on its page

## Metadata
- **ID**: T-005 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O1, O4 · TRD section(s) §2 (Extract flow), ADR-004; CONSTITUTION §1.3, §7
- **Depends on**: T-003 · **Wave**: 3
- **Files likely touched**: `app/domain/` (page text with word offsets, span→words alignment, box merging), `tests/unit/domain/`
- **Design**: likely-needed (the offset-alignment algorithm is the core of box correctness and has several plausible shapes)

## Goal
Given a page's OCR words and the character spans of the person names found in that
page's text, produce one bounding box (in PDF points) per real occurrence of each name —
exact, without guessing by string search. This is what makes a reported name verifiable
on the page.

## User Story
As a compliance reviewer
I want one box per place a name actually appears, tightly around that name
So that I can check each mention individually, including repeated mentions of the same person

## Functional Description
- Page text construction (domain): from a `Page`'s ordered words, build the text by joining words of the same line with a single space and different lines with `\n`; record for every word its `[start, end)` character offsets in that text. The same text is what the recognizer (T-004) receives, so offsets are shared.
- Alignment: for each entity span `[start, end)`, select the words whose offsets overlap the span. Overlap = at least one character in common.
- Trimming: punctuation attached to a word but outside the span (`Thompson,` when the span ends before the comma) does not change which word is selected; the box is the whole OCR word (OCR gives no sub-word boxes) — documented limitation.
- Box merging: selected words are grouped by line; each group becomes one box = the union rectangle (min x, min y, max right, max bottom) of its words. A name entirely on one line → one occurrence with one box. A name broken across two lines → two occurrences (one per line segment), both carrying the full span text as the name.
- Occurrence = name text (span text, honorific already trimmed by T-004), 0-based page index, box in points. Repeated names yield separate occurrences, ordered by page, then by position in the page text.
- A span that overlaps no word (should not happen; defensive) is dropped and logged as `alignment_span_unmatched` with page index and offsets — never with the name.

## Main Flow
1. Use case passes page 0 of the memo (words in points) and spans `[{start, end}]` for `Margaret Thompson` (twice) and `Robert Chen`.
2. Domain builds the page text and the word offset index.
3. Domain maps each span to its words and merges their boxes per line.
4. Result: 3 occurrences — two `Margaret Thompson` boxes (different y) and one `Robert Chen` box — each on page 0.

## Alternative Flows
- **Name followed by punctuation**: Given words `["From:", "Margaret", "Thompson,", "CEO"]` and the span of `Margaret Thompson` → one box = union of `Margaret` and `Thompson,`; `From:` and `CEO` are not included.
- **Name wraps lines**: Given `"…managed by David"` / `"Nakamura and his team…"` and one span covering both words → two occurrences on the same page, one per line.
- **Unmatched span**: Given a span beyond the text length → dropped and `alignment_span_unmatched` logged.

## Acceptance Criteria
1. **Offsets round-trip**
   - Given any page of words
   - When the page text and offset index are built
   - Then for every word `text[start:end] == word.text`, words on one line are separated by exactly one space and lines by `\n`
2. **Exact words, nothing more**
   - Given words `From:`, `Margaret`, `Thompson,`, `CEO` on one line and a span covering `Margaret Thompson`
   - When alignment runs
   - Then one occurrence is produced whose box equals the union of the `Margaret` and `Thompson,` boxes exactly
3. **One box per real occurrence**
   - Given a page where `Richard Hernandez` appears on 3 different lines and 3 spans
   - When alignment runs
   - Then 3 occurrences are returned, with 3 distinct boxes, ordered top to bottom
4. **Line wrap splits, never spans**
   - Given a span whose words lie on two lines
   - When alignment runs
   - Then two occurrences are returned and neither box's height exceeds the taller line's height
5. **Boxes stay in points and on the page**
   - Given words in points on a 612×792 page
   - When any occurrence box is produced
   - Then its coordinates are a union of input word boxes (no rescaling) and lie inside the page

## Technical Notes *(only if applicable)*
- Pure domain: no OCR or NER calls; tests use hand-built `Word`s and spans — CONSTITUTION §7 (domain unit tests, no mocks).
- No fuzzy string search is used to locate names — TRD ADR-004.

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
- [ ] The alignment module imports nothing outside stdlib and `app.domain`.
- [ ] The page-text builder used here is the same function whose output T-004's recognizer receives (single source of offsets).
