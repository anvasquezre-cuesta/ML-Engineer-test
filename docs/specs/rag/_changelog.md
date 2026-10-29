# Changelog — rag

## 2026-10-21 — CR-002: relevance gate removed
- Live smoke test: "Who is the CEO of the company?" / "Who wrote the memo?" answered
  "not found" (top scores −3.00 / −6.47 < gate −2.59). The latter scores below an
  unanswerable question, so no threshold works. Gate removed; the LLM decides.
- Golden q14/q15 added. `eval_retrieval.py` hit@5 12/12, hit@1 11/12;
  `eval_answers.py` pass^3 15/15, 0 ungrounded.

## 2026-10-21 — Implementation
- T-001…T-006 implemented, one commit each (see `_manifest.md`), full gate green per
  ticket (final: 818 unit + 47 integration, 1 live-LLM test skipped without a key).
- Evals: `time_reranker.py` mmarco p50 1.55 s / 20 pairs; `eval_retrieval.py` hit@5 10/10,
  hit@1 10/10, gate calibrated at −2.59 (window −4.49 … −0.70); `eval_answers.py` not run
  yet — needs `DOCINTEL_LLM_API_KEY`.
- Divergences from the plan (acceptance criteria unchanged):
  - T-003: `ChromaVectorStore.close()` uses `client.close()` — `clear_system_cache()` alone
    does not release Windows file locks while references live (verified); the
    collection name needs ≥ 3 chars (Chroma rule, now a `Settings` constraint); the
    extraction e2e now uses a temporary vector store; the fast suite takes ~25 s instead
    of ~7 s because `app.main` imports torch.
  - T-004/T-005: the reranker and `RetrieveChunks` were wired into `build_container` by
    T-006, their first consumer (no unused objects at startup).
  - T-005: `eval_retrieval.py` also reports hit@1 — the samples make only 5 chunks, so
    top-5 holds everything and hit@5 alone proves little.
  - T-006: openai 3.x is built on `httpx2`, not `httpx` (test transport and import-linter
    updated); `GroundedAnswer` counts invalid citations; `answer_completed` logs
    `sources_count` + `invalid_citations`; an empty `DOCINTEL_LLM_API_KEY` counts as
    missing.

## 2026-10-21 — Approval
- Approved by the human gate (Pablo): T-004 v2 (after CR-001).

## 2026-10-21 — CR-001 (Type B)
- Spike S6 preliminary run: bge-reranker-v2-m3 21.1 s / 20 pairs on CPU (budget 2 s).
- TRD §8.2, §15 S6 and ADR-014 updated: default reranker
  `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingual, 2.0 s).
- Regenerated: T-004 (v1→v2). Back to pending-approval.

## 2026-10-21 — Approval
- Approved by the human gate (Pablo): T-001…T-006. Before approval, at his request:
  T-001 / ADR-015 now split an oversized paragraph only between sentences (then words),
  never at visual lines; spec.md states explicitly that different documents never
  overwrite each other and only an identical PDF replaces its own chunks.

## 2026-10-21 — Initial generation
- Created T-001…T-006 from `README.md` (PRD) + `docs/trds/document-intelligence-trd.md`
  (v0.1 with the 2026-10-21 RAG revisions) + ADR-014 + ADR-015, scoped to TRD §14 phase
  P2. All pending-approval.
