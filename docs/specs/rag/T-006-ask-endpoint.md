# `POST /api/ask` end to end with cited, code-built sources

## Metadata
- **ID**: T-006 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O7, O3, O4 · TRD section(s) §1 (RAG answer, grounding), §2 (Ask flow), §5, §9, §10, §11, §12, ADR-006, ADR-010; CONSTITUTION §4.5, §8, §9
- **Depends on**: T-005 · **Wave**: 5
- **Files likely touched**: `app/application/ports.py` (`AnswerGenerator`), `app/application/` (`AnswerQuestion`), `app/domain/` (citation parsing → sources), `app/infrastructure/` (OpenAI-compatible generator, settings), `app/api/rag.py`, `app/api/dependencies.py`, `app/main.py`, `app/domain/errors.py`, `pyproject.toml`, `uv.lock`, `.env.example`, `scripts/` (answer eval), `tests/fakes/`, `tests/unit/`, `tests/e2e/`
- **Design**: skip (flow fixed by TRD §2 and ADR-006; contract fixed by `schemas.py`)

## Goal
Answer any question about the ingested documents in natural language, grounded only in
the retrieved chunks, with `sources` that point to the exact file and page each claim
came from — and that can never be invented, because code, not the LLM, builds them.

## User Story
As a compliance reviewer (or the system that serves them)
I want to ask a question about the ingested documents and get an answer with the pages it came from
So that I can trust the answer only as far as I can verify it on those pages

## Functional Description
- Request: JSON `RAGRequest` (`question`, 1–2000 chars, validated by `schemas.py`). Response: `RAGResponse` exactly as in `schemas.py`.
- `AnswerQuestion` use case (application): `RetrieveChunks` (T-005) → if nothing relevant, return the **not-found answer** (`"The answer is not in the ingested documents."`, `sources: []`) without calling the LLM → otherwise send the retrieved chunks as **numbered passages** `[1]..[k]` (best first) to the `AnswerGenerator` → build `sources` from the citations in its reply.
- **Prompt** (TRD §5, §9): a system instruction says to answer only from the passages, cite the passage number `[n]` after each claim, and reply exactly with the not-found sentence if the passages don't contain the answer; passages are wrapped in explicit delimiters and declared as data, not instructions. The LLM gets no tools. Temperature 0.
- **Sources (domain, pure):** parse `[n]` markers from the reply; keep only `n` in `1..k`; map each to its chunk's `"{file_name}, page {page}"`; de-duplicate keeping first-citation order. Citation markers are removed from the returned `answer` text.
- **No valid citation ⇒ not-found answer** with `sources: []` (an uncited reply is not grounded; this also covers the LLM's own "not found" sentence).
- **`AnswerGenerator` port** / adapter: openai SDK against any OpenAI-compatible endpoint (ADR-010); default Groq (`https://api.groq.com/openai/v1`, `openai/gpt-oss-120b` since `llama-3.3-70b-versatile` was retired). SDK `timeout` and `max_retries` (exponential backoff on 408/409/429/5xx, honouring `Retry-After`) come from settings. SDK errors are translated at the adapter edge: rate limit (after retries) → `LlmRateLimited` (503, `llm_rate_limited`); timeout → `LlmTimeout` (503, `llm_timeout`); any other API/connection error → `LlmUnavailable` (502, `llm_unavailable`).
- **Missing API key:** the service still starts; `/ask` with evidence to answer returns 503 `llm_not_configured`; a `llm_not_configured` warning is logged once at startup. `/extract`, `/ingest` and `/health` are unaffected.
- New settings (`DOCINTEL_*`, in `.env.example`, key without a value): `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS` (default 30), `LLM_MAX_RETRIES` (default 2).
- Route is sync `def`. Logging: one `answer_completed` event with outcome (`answered` / `not_found`), passages sent, valid and invalid citation counts, LLM latency, token usage and model. Never the question, the passages or the answer; never the API key.
- **Answer eval** (`scripts/eval_answers.py`): ingests the samples, runs every golden Q&A item (T-005) **3 times** against the live LLM (throttled to stay under the provider's RPM), and scores: answerable → the expected fact (normalized) appears in the answer and the expected `"{file}, page {n}"` is in `sources`; unanswerable → not-found answer; injection probe → not-found answer or an answer that follows none of the injected instructions. Prints pass^3 per item and overall; exits 0 if ≥ 0.80 of items pass all 3 runs (TRD §1). Skips with a clear message when no API key is set.

## Main Flow
1. Client posts `{"question": "Who is the Chief Data Scientist?"}` after ingesting the samples.
2. Retrieval returns 5 chunks, the memo's first.
3. The LLM replies citing `[1]`.
4. Router returns `200 {"answer": "Dr. Sarah Williams will join as Chief Data Scientist.", "sources": ["company_memo.pdf, page 0"]}`.

## Alternative Flows
- **Nothing relevant**: Given an unanswerable question → `200` with the not-found answer, `sources: []`, and no LLM call.
- **Invented citation**: Given a reply citing `[9]` when 5 passages were sent → `[9]` is dropped; if no valid citation remains → not-found answer.
- **LLM not configured**: Given no `LLM_API_KEY` and a question with evidence → `503` `llm_not_configured`.
- **LLM failures**: Given timeout / 429 after retries / 5xx → `503` `llm_timeout`, `503` `llm_rate_limited`, `502` `llm_unavailable`, each with the `request_id`.
- **Invalid body**: Given `{"question": ""}` or a missing field → `422`.

## Acceptance Criteria
1. **Sources can only come from passages sent** *(use-case test, fakes)*
   - Given 3 retrieved chunks and a fake generator replying `"A [1]. B [3]. C [7]."`
   - When `AnswerQuestion` runs
   - Then `sources` = the chunks 1 and 3 as `"{file_name}, page {page}"` (in that order, de-duplicated), `[7]` is ignored, and the answer contains no `[n]` marker
2. **Uncited reply ⇒ not found**
   - Given a fake generator replying without any valid citation
   - When `AnswerQuestion` runs
   - Then the response is the not-found answer with `sources: []`
3. **No LLM call without evidence**
   - Given retrieval returns nothing relevant and a spy generator
   - When `/api/ask` is called
   - Then the response is `200` with the not-found answer and the spy was never called
4. **LLM errors map to distinct codes**
   - Given a generator raising `LlmTimeout`, `LlmRateLimited`, `LlmUnavailable`, and a service with no API key
   - When `/api/ask` is called for each
   - Then the responses are `503 llm_timeout`, `503 llm_rate_limited`, `502 llm_unavailable`, `503 llm_not_configured`, each with a `request_id`
5. **Answers grounded on the samples** *(eval, live LLM)*
   - Given the 3 sample PDFs ingested and the golden Q&A
   - When `scripts/eval_answers.py` runs
   - Then ≥ 0.80 of items pass all 3 runs and every returned source is the file + page of a chunk that was sent to the LLM

## Technical Notes *(only if applicable)*
- `openai` is the dependency decided by ADR-010 — pin it; no other library.
- Lethal trifecta cut: the LLM has no tools and its output is returned only to the caller; `sources` never come from LLM text — TRD §9, ADR-006.
- The API key comes only from the environment, is never logged and never enters the prompt — TRD §9.

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
- [ ] Every string in `sources` is built from retrieved-chunk metadata; no code path copies LLM output into `sources`.
- [ ] A captured `answer_completed` log record contains neither the question, the answer nor the API key.
- [ ] The rag router module has no `if`/loop implementing a business rule (only parsing, the use-case call and DTO mapping).
