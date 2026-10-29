# Rerank (question, chunk) pairs with a cross-encoder (spike S6)

## Metadata
- **ID**: T-004 · **Version**: v2 · **State**: approved
- **Traces to**: PRD objective(s) O7, O4 · TRD section(s) §3 (Reranker adapter), §8.2, §12, §15 S6, ADR-014
- **Depends on**: T-003 · **Wave**: 3
- **Files likely touched**: `app/application/ports.py` (`Reranker`), `app/infrastructure/` (cross-encoder reranker, settings), `app/main.py`, `app/domain/errors.py`, `.env.example`, `scripts/` (latency spike), `tests/fakes/`, `tests/integration/`
- **Design**: skip (one-method port; model and runtime fixed by ADR-014)

## Goal
Give retrieval a model that reads the question and each candidate chunk together and
scores how well the chunk answers it — the step that orders candidates precisely and
gives the "not found" gate a usable score — and measure that it is fast enough on CPU.

## User Story
As the retrieval step of `/api/ask`
I want each candidate chunk scored against the question by a cross-encoder
So that the best chunks reach the LLM first and irrelevant ones can be recognized as such

## Functional Description
- **`Reranker` port:** given a question and a sequence of chunk texts, return one relevance score per text, in input order (higher = more relevant). An empty sequence returns an empty list without calling the model.
- **Adapter:** sentence-transformers `CrossEncoder` with `RERANKER_MODEL` (default `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, chosen by the preliminary S6 run — ADR-014 amendment, CR-001), loaded once at startup, CPU. Scores are the model's raw outputs — logits, no sigmoid — and the gate threshold in T-005 is calibrated on this scale.
- Model load failure → `RerankerUnavailable` (infrastructure error, 503, `error.code = "reranker_unavailable"`) raised at startup, naming the model, never the text.
- **Spike S6:** `scripts/time_reranker.py` scores 20 pairs (question + 250-token passages) 10 times on the dev box and prints p50/p95 latency and model load time. **Budget: p50 ≤ 2 s for 20 pairs.** The preliminary run already recorded in ADR-014 (bge-v2-m3 21.1 s, bge-base 6.2 s, mmarco 2.0 s, MiniLM-L6 0.7 s) is re-measured with the script for the configured model and the numbers are updated in ADR-014. If it is over budget, lower `RETRIEVAL_CANDIDATES` (T-005) by config. There is always a reranker.
- New setting (`DOCINTEL_RERANKER_MODEL`), documented in `.env.example`.

## Main Flow
1. Retrieval passes a question and 20 candidate chunk texts.
2. The adapter scores the 20 pairs in one batch.
3. It returns 20 scores in input order.

## Alternative Flows
- **No candidates**: Given an empty sequence → `[]`, model not called.
- **Model cannot be loaded**: Given a non-existent `RERANKER_MODEL` → startup fails with `reranker_unavailable`.
- **Over the latency budget**: Given S6 p50 > 2 s for the configured model → `RETRIEVAL_CANDIDATES` lowered by config and the numbers recorded in ADR-014.

## Acceptance Criteria
1. **Relevant passage scores higher** *(integration, real model)*
   - Given the question `"Who chairs the board?"` and two passages, one stating Richard Hernandez is Chairman of the Board and one about cloud migration
   - When they are scored
   - Then the chairman passage gets the higher score
2. **Order and length preserved** *(integration)*
   - Given 5 passages
   - When scored
   - Then exactly 5 scores are returned, the i-th for the i-th passage (checked by permuting the input and comparing)
3. **Multilingual** *(integration)*
   - Given the Spanish question `"¿Quién preside la junta?"` and the same two English passages
   - When scored
   - Then the chairman passage gets the higher score
4. **Spike S6 recorded**
   - Given `scripts/time_reranker.py`
   - When it runs on the dev box
   - Then it prints load time and p50/p95 for 20 pairs, and ADR-014 records the measured numbers and the resulting default model
5. **Empty input short-circuits**
   - Given an adapter whose model is a spy
   - When it is called with no passages
   - Then it returns `[]` and the model is not invoked

## Technical Notes *(only if applicable)*
- No new dependency: `CrossEncoder` ships with sentence-transformers, added in T-003 — ADR-014.
- Integration tests are marked `integration` and skip with a clear reason if the model cannot be downloaded — CONSTITUTION §7.

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
- [ ] ADR-014 contains the S6 latency numbers (load time, p50, p95) measured by `scripts/time_reranker.py`.
- [ ] The model is loaded once in the composition root, never per request.
