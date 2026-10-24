# Decisions

## Use of AI tools

AI assistants (Claude via Claude Code) were used throughout this build, as the
README anticipates. What they were used for:

- **Scaffolding and iteration**: stories were planned and implemented through
  BMad-style ticketing; code was written with AI assistance and every line was
  reviewed before commit.
- **Test generation**: the pytest suites under `tests/` (tracer, all-pages,
  fuzzy, upload-validation) were drafted with AI and checked against the
  documented contract in `README.md`.
- **A manual bug-hunt that found a real defect**: driving the live server with
  curl (rather than only running the suite) exposed a crash in
  `POST /api/extract` when `names_json` contained plain strings instead of
  `{first_name, last_name}` pairs — the suite was green because no test posted
  non-empty `names_json`. Fixed at the router boundary with two regression
  tests (`bb52e65`).
- **Documentation**: this file and `DESIGN.md` were drafted with AI assistance
  and edited by hand.

The engineering decisions recorded in `DESIGN.md` were made by reviewing and
owning the resulting code, per the README's "own every line" condition.

## RAG tracer-bullet schema contract (story 2.1)

This story added no fields to `app/models/schemas.py`. The existing
`IngestResponse`, `RAGRequest`, and `RAGResponse` models were used as-is;
the API contract is unchanged.

## Retry discipline on external calls (post-2.1)

All external service calls (embedding, vector store operations, LLM calls)
are wrapped with `with_retries()` from `app/core/http.py`, providing
configurable timeout and fixed backoff. This ensures transient failures
are handled gracefully rather than bubbling immediately to the caller.

## Deterministic ingest via content-derived IDs (post-2.1)

Chunk IDs are derived from document content hash (`sha256` of file bytes),
page number, and chunk index. This makes ingest idempotent: re-ingesting the
same document produces identical chunk IDs, enabling upsert semantics in
Chroma rather than duplicate entries.

## LangChain kwarg hygiene (post-2.1)

Removed dead `retry_wait` kwarg from `ChatOpenAI` initialization and ensured
the adapter passes no legacy kwargs. The adapter uses explicit `timeout` and
`max_retries` parameters instead of relying on global or deprecated settings.

## Schema contract affirmed across epics 1 and 2

`app/models/schemas.py` remains byte-identical to the skeleton commit
(b091afa). No fields were added, removed, or renamed across either epic.
The end-to-end path through the real application is exercised by the test
suite: tracer-bullet happy path, real-PDF all-pages tests, and RAG tests.
