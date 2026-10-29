# Rank chunks by exact terms (BM25)

## Metadata
- **ID**: T-002 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O7, O4 · TRD section(s) §3 (Lexical ranking), ADR-014, ADR-005 (normalizer reused)
- **Depends on**: none · **Wave**: 1
- **Files likely touched**: `app/domain/` (new lexical ranking module), `tests/unit/domain/`
- **Design**: skip (Okapi BM25 is a fixed formula; parameters fixed by ADR-014)

## Goal
Give retrieval an exact-term ranking — names, codes, figures — to complement the
meaning-based ranking, because dense retrieval is weakest on exactly those terms.

## User Story
As the retrieval step of `/api/ask`
I want the stored chunks ranked by how well they match the question's exact words
So that a chunk containing a rare name or figure from the question is not lost to semantically "close" but wrong chunks

## Functional Description
- Input: a question string and a sequence of `(chunk_id, text)` pairs; a limit `n`. Output: up to `n` chunk ids with their BM25 score, best first; chunks scoring 0 are excluded.
- **Okapi BM25** with `k1 = 1.5`, `b = 0.75`, IDF `ln(1 + (N − df + 0.5) / (df + 0.5))` (always positive), document length in tokens, average over the given chunks.
- **Tokenization:** text is normalized with the existing name normalizer (`normalize_name`: casefold, accent strip, punctuation collapse) and split on whitespace, so `González` → `gonzalez`, `O’Brien` → `o`, `brien` and `12%` → `12`, exactly as the extraction epic normalizes names.
- Ties keep the input order (stable), so results are deterministic.
- Pure function: no I/O, no state, no index kept between calls — the caller passes the chunks every time (ADR-014: no in-process index).
- Empty question tokens, or no chunks → empty result.

## Main Flow
1. Retrieval passes the question and all stored chunks with `n = 10`.
2. The ranker scores each chunk with BM25 over normalized tokens.
3. It returns the best 10 chunk ids with score > 0, best first.

## Alternative Flows
- **No chunks**: Given an empty chunk sequence → empty result.
- **No term overlap**: Given a question sharing no token with any chunk → empty result.
- **Question of only punctuation**: Given `"???"` → empty result.
- **Invalid limit**: Given `n < 1` → `ValueError`.

## Acceptance Criteria
1. **Rare exact term wins**
   - Given three chunks where only one contains `Okonkwo` and all contain `the`, `team`
   - When the question is `"What does Okonkwo handle?"`
   - Then that chunk is ranked first
2. **Accent- and case-insensitive**
   - Given a chunk containing `María González`
   - When the question is `"maria gonzalez"`
   - Then that chunk is returned with a score > 0
3. **Known value**
   - Given a fixed 3-chunk corpus and question in the test
   - When it is ranked
   - Then each score equals the hand-computed BM25 value (k1 = 1.5, b = 0.75) within 1e-6
4. **Zero-score chunks excluded and limit applied**
   - Given 5 chunks of which 3 share a token with the question
   - When ranked with `n = 2`
   - Then exactly 2 ids are returned, both from the 3 matching chunks, best first
5. **Deterministic ties**
   - Given two identical chunks
   - When ranked
   - Then they are returned in input order on every run

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
- [ ] No BM25 library is added to `pyproject.toml`; tokenization calls the existing `normalize_name`.
- [ ] The module keeps no module-level or instance state between calls.
