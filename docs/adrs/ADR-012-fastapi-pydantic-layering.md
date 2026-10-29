# ADR-012 — FastAPI and Pydantic are confined to the driving adapter

- **Status:** accepted
- **Date:** 2026-10-21
- **Related:** TRD ADR-001 (hexagonal, ports in application), `CONSTITUTION.md` §2.1

## Context

FastAPI is the stack's only opinionated framework. It encourages putting logic in path
operations and using `Depends` as a service locator, and Pydantic models are tempting to
reuse as domain entities. The PRD fixes the HTTP contract in `app/models/schemas.py`
(Pydantic) and weights "thin routers, business logic testable without HTTP" and
"services depend on abstractions" at 20 %.

## Options considered

1. **FastAPI-centric:** logic in routers, Pydantic models everywhere (domain = schemas).
   Fewest files; but domain becomes coupled to the HTTP contract and to Pydantic, and
   use cases are only testable through HTTP.
2. **Pydantic in the domain, FastAPI only at the edge:** domain entities as Pydantic
   models for free validation. Less mapping code; but the domain imports a framework
   and the fixed contract and the domain model would drift together.
3. **Both confined to the driving adapter (chosen):** domain = stdlib dataclasses/enums,
   application = plain classes + `Protocol` ports, FastAPI + `schemas.py` only in
   `app/api/`, `pydantic-settings` only in infrastructure/composition root.

## Decision

Option 3. Domain and application import neither `fastapi` nor `pydantic`. Routers parse
and validate input, call a use case, and map the domain result to the `schemas.py` DTO.
The lifespan in `app/main.py` is the composition root: it reads `Settings`, builds each
adapter once, and exposes the wired use cases through dependency providers. Enforced by
import-linter `forbidden` contracts.

## Consequences

- ➕ Use cases and domain are testable in-process with fakes, no HTTP client needed.
- ➕ The fixed contract can't leak into business rules; changing a model library touches
  only the edge.
- ➖ Explicit DTO ↔ domain mapping functions (small, but extra code).
- ➖ Validation of domain invariants is written by hand in dataclass `__post_init__`
  instead of being free from Pydantic.
