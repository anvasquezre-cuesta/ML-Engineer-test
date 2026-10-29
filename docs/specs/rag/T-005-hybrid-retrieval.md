# Retrieve the most relevant chunks for any question, with a relevance gate

> **Superseded in part by [CR-002](change-requests/CR-002.md):** the relevance gate was
> removed; retrieval always returns the top-k reranked chunks and the LLM decides
> "not found". The gate criteria below are history.

## Metadata
- **ID**: T-005 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O7, O4 · TRD section(s) §1 (RAG retrieval metric), §2 (Ask flow), §10, §11, ADR-014
- **Depends on**: T-002, T-003, T-004 · **Wave**: 4
- **Files likely touched**: `app/application/` (`RetrieveChunks`), `app/infrastructure/settings.py`, `app/main.py`, `.env.example`, `tests/golden/` (RAG Q&A set), `scripts/` (retrieval eval), `tests/unit/application/`, `tests/unit/test_golden_set.py`
- **Design**: likely-needed (shape of the retrieval result that T-006 consumes; gate calibration procedure)

## Goal
For any question, find the few chunks most likely to contain the answer — combining
meaning-based and exact-term search, then reranking — and decide deterministically when
nothing relevant exists, so the LLM is never called without evidence. Prove it on a
golden question set.

## User Story
As the `/api/ask` use case
I want the best few chunks for a question, or a clear "nothing relevant" verdict
So that answers are built only from evidence and unanswerable questions cost no LLM call

## Functional Description
- `RetrieveChunks` (application), built by the composition root with `Embedder`, `VectorStore`, `Reranker` and settings. Input: a question. Output: either up to `TOP_K` retrieved chunks (text, `document_id`, `file_name`, `page`, `chunk_index`, rerank score), best first, or **nothing relevant**.
- Pipeline (ADR-014), for every question alike — no question-type special cases:
  1. **Dense:** embed the question → top `RETRIEVAL_CANDIDATES` from the store.
  2. **Lexical:** read all stored chunks through the `VectorStore` port → BM25 (T-002) → top `RETRIEVAL_CANDIDATES`.
  3. **Union** of both lists, de-duplicated by chunk id.
  4. **Rerank** the union with the `Reranker` (T-004); keep the best `TOP_K`.
  5. **Gate:** best rerank score < `RERANK_MIN_SCORE` ⇒ nothing relevant.
- Empty store ⇒ nothing relevant, without calling embedder or reranker.
- **Golden Q&A** (`tests/golden/questions.json`, ~12 items, written by hand from the sample PDFs): answerable items with expected `file_name` + `page` + an expected fact string; unanswerable items (topic absent from all documents); one prompt-injection probe (a question that asks to ignore instructions / reveal the prompt). Items vary wording (paraphrases, partial names, a Spanish question) — the set tests generality, it does not drive design.
- **Retrieval eval** (`scripts/eval_retrieval.py`): ingests the 3 sample PDFs into a temporary store, runs `RetrieveChunks` on every golden question, and prints hit@k (expected file + page among the retrieved chunks), the top rerank score of every item, and the gate outcome. It also prints the **calibration window**: lowest top score among answerable items vs highest among unanswerable ones; `RERANK_MIN_SCORE`'s default is set inside that window and the chosen value with its window is recorded in ADR-014. Exit 0 only if hit@k = 100 % and every unanswerable item is gated.
- New settings (`DOCINTEL_*`, in `.env.example`): `RETRIEVAL_CANDIDATES` (default 10), `TOP_K` (default 5), `RERANK_MIN_SCORE` (default from calibration).
- Logging: one `retrieval_completed` event with candidate counts (dense, lexical, union), returned count, top score, gate outcome and per-stage durations. No question text, no chunk text.

## Main Flow
1. `/api/ask` passes `"Who will manage the Atlas project?"`.
2. Dense and BM25 each return up to 10 candidates; their union is reranked.
3. The best score clears the gate; the 5 best chunks are returned, the memo's chunk first.

## Alternative Flows
- **Nothing relevant**: Given a question about a topic absent from every document → best score below `RERANK_MIN_SCORE` → nothing relevant.
- **Empty store**: Given no document ingested → nothing relevant; embedder and reranker not called.
- **Fewer chunks than `TOP_K`**: Given a store with 3 chunks → at most 3 returned.
- **Store failure**: Given the `VectorStore` raises `VectorStoreUnavailable` → it propagates (503 at the API, T-006).

## Acceptance Criteria
1. **Golden retrieval hit@k = 100 %** *(eval)*
   - Given the 3 sample PDFs ingested and the golden Q&A
   - When `scripts/eval_retrieval.py` runs
   - Then every answerable item has its expected file + page among the retrieved chunks, every unanswerable item is gated, and the script exits 0
2. **Both candidate sources reach the reranker**
   - Given fakes where the dense side returns only chunk A and BM25 returns only chunk B
   - When `RetrieveChunks` runs
   - Then the reranker receives both A and B exactly once
3. **Order and cut by rerank score**
   - Given 8 candidates with scripted rerank scores and `TOP_K = 5`
   - When `RetrieveChunks` runs
   - Then the 5 highest-scoring chunks are returned, best first
4. **Gate**
   - Given scripted rerank scores whose maximum is below `RERANK_MIN_SCORE`
   - When `RetrieveChunks` runs
   - Then the result is nothing relevant
5. **Empty store short-circuits**
   - Given an empty fake store and spy embedder/reranker
   - When `RetrieveChunks` runs
   - Then the result is nothing relevant and neither spy was called

## Technical Notes *(only if applicable)*
- BM25 runs over chunks read at query time — no index is kept in the process — ADR-014.
- The golden Q&A is validated by `tests/unit/test_golden_set.py` (schema: each answerable item names an existing sample file and page) — TRD §11.

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
- [ ] `RetrieveChunks` has no branch on the question's content (no keyword, name or language checks).
- [ ] ADR-014 records the calibration window and the chosen `RERANK_MIN_SCORE` printed by `scripts/eval_retrieval.py`.
