# Walking skeleton: hexagonal service with health, config, logging and quality gate

## Metadata
- **ID**: T-001 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O3, O5 · TRD section(s) §2, §8, §11, ADR-001; CONSTITUTION §1, §2.1, §4.5, §6, §8, §9; ADR-012
- **Depends on**: none · **Wave**: 1
- **Files likely touched**: `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`, `app/main.py`, `app/api/`, `app/application/`, `app/domain/`, `app/infrastructure/` (settings, logging), removal of `app/services/*.py` stubs, `tests/`
- **Design**: likely-needed (fixes the package layout, error hierarchy, settings and logging contracts every later ticket builds on)

## Goal
Give the project a running, enforceable foundation: the hexagonal package layout, one
typed configuration object, structured JSON logging with a request id, the error
hierarchy mapped to HTTP, and a validation gate that fails on layer violations. Every
later ticket plugs into this without re-deciding it.

## User Story
As an operator deploying the service
I want a liveness endpoint, environment-driven configuration and structured logs from day one
So that I can run, probe and debug the service before any extraction feature exists

## Functional Description
- The app exposes `GET /health` returning `200` with body `{"status": "ok"}` (shape from `HealthResponse`). Health goes direct to the router — no use case (CONSTITUTION §1.4).
- Packages `app/domain`, `app/application`, `app/infrastructure`, `app/api` exist. `app/models/schemas.py` stays untouched. The skeleton stubs in `app/services/` are deleted (TRD ADR-001).
- A single `Settings` object (infrastructure) reads environment variables with prefix `DOCINTEL_`, has defaults for every key, and is documented key-by-key in `.env.example`. At this ticket it holds at least: log level, max upload size (bytes), max page count, render DPI, OCR languages, OCR confidence floor, fuzzy-match threshold. Values that are invalid (e.g. threshold outside 0..1, DPI ≤ 0) make startup fail with a message naming the key.
- `app/main.py` is the composition root: an app factory with a lifespan that loads `Settings` once. No adapter is instantiated anywhere else (CONSTITUTION §4.5).
- Logging emits one JSON object per line with `timestamp` (UTC ISO-8601), `level`, `event`, `request_id`, plus extra structured fields. A middleware assigns a `request_id` per request (reuses an incoming `X-Request-ID` header if present), returns it in the `X-Request-ID` response header, and logs `request_completed` with method, path, status and duration in ms.
- Error hierarchy in the domain: `DomainError` and `InfrastructureError` base classes (each carrying a stable machine `code`). Exception handlers map `DomainError` → 4xx and `InfrastructureError` → 503, both with JSON body `{"error": {"code": ..., "message": ..., "request_id": ...}}`. Unhandled exceptions → 500 with the same shape, logged with stack trace, never leaking internals in the body.
- Tooling configured in `pyproject.toml`: ruff (lint + format), mypy strict on `app/`, import-linter contracts (domain imports no other app layer nor `fastapi`/`pydantic`; application imports only domain; api and infrastructure never import each other except via `app/main.py`), pytest with an `integration` marker excluded from the fast suite.
- Dependencies pinned for Python 3.12 (`.python-version`), spaCy model as a pinned wheel URL (CLAUDE.md gotcha), `rapidfuzz` instead of `thefuzz` (TRD ADR-005). Libraries not needed until the RAG epic may stay declared but unused.

## Main Flow
1. Operator runs `uv sync --extra dev` and `uv run uvicorn app.main:app`.
2. System loads `Settings` from environment/defaults and starts.
3. Operator calls `GET /health`.
4. System responds `200 {"status":"ok"}` with an `X-Request-ID` header and logs one JSON `request_completed` line containing that id.
5. Developer runs the validation gate (ruff, mypy, lint-imports, pytest) and all pass.

## Alternative Flows
- **Invalid configuration**: Given `DOCINTEL_FUZZY_THRESHOLD=1.7` → startup fails with an error naming `DOCINTEL_FUZZY_THRESHOLD`; the server does not start.
- **Layer violation**: Given a module in `app/domain` imports `fastapi` → `lint-imports` exits non-zero with a message naming the broken contract.
- **Unhandled exception in a route**: Given a route raises an unexpected error → response 500 with `{"error":{"code":"internal_error",...,"request_id":...}}`; the log line contains the stack trace and the same `request_id`.

## Acceptance Criteria
1. **Liveness**
   - Given the app is running with default settings
   - When a client sends `GET /health`
   - Then the response is `200`, body `{"status":"ok"}`, and header `X-Request-ID` is present
2. **Configuration is environment-driven and validated**
   - Given `DOCINTEL_RENDER_DPI=200` is set
   - When `Settings` is loaded
   - Then `render_dpi == 200`; and given `DOCINTEL_FUZZY_THRESHOLD=1.7`, loading raises an error naming that key
3. **Structured request log**
   - Given a request with header `X-Request-ID: abc-123`
   - When it completes
   - Then exactly one log record with `event="request_completed"`, `request_id="abc-123"`, `status`, `duration_ms` is emitted as valid JSON, and the response echoes `X-Request-ID: abc-123`
4. **Error mapping**
   - Given test routes raising a `DomainError` subclass, an `InfrastructureError` subclass and a bare `ValueError`
   - When each is called
   - Then responses are 4xx, 503 and 500 respectively, each with body `{"error":{"code","message","request_id"}}` and no stack trace in the body
5. **Quality gate enforces the architecture**
   - Given the repository at the end of this ticket
   - When `ruff check`, `ruff format --check`, `mypy app`, `lint-imports` and `pytest -m "not integration"` run
   - Then all exit 0; and a deliberately added `import fastapi` in `app/domain` makes `lint-imports` exit non-zero

## Technical Notes *(only if applicable)*
- `app/models/schemas.py` field names and types must not change — README §What you're building.
- No literal hosts, ports, model names, thresholds or DPI outside `Settings` — CONSTITUTION §6.
- Logs never contain person names or document text — CONSTITUTION §9.

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
- [ ] `app/services/` no longer exists and `git diff` shows `app/models/schemas.py` unchanged.
- [ ] Every `Settings` field appears in `.env.example`; `CLAUDE.md` build commands are no longer marked PENDING and match the real ones.
