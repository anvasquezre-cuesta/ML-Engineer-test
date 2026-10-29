# Code Constitution · Document Intelligence Service

**Version:** v1.0 · **Date:** 2026-10-21
**Audience:** programmers (human and AI agents) writing code in this repo.
**Scope:** code architecture principles, patterns, and engineering standards. **Not**
system architecture (that's the TRD and its ADRs) nor development process (that's the
PIV loop and the skills).

---

## 0. Preamble

### 0.1 What this document is

The minimal set of principles, architectural concepts, and patterns that govern how we
write software here. It doesn't say which library we use or which exact folder a port
lives in — it says **why** and **under which principles** we make those decisions.
Tools change; principles stay.

### 0.2 How it relates to the other documents

- **`CONSTITUTION.md`** *(this)* — how good code is written. Changes rarely. Normative.
- **PRD** — WHAT and WHY of the product. Here: [`README.md`](README.md).
- **TRD** — HOW at system level: architecture decisions and **ADRs**
  ([`docs/trds/document-intelligence-trd.md`](docs/trds/document-intelligence-trd.md)).
  TRD decisions are **not reopened** while implementing; if one looks wrong, propose the
  change as its own CR/ADR.
- **`CLAUDE.md`** — short operational pointer always loaded by agents; descriptive
  (how the code IS). Where CLAUDE.md and this document disagree, this document states
  the target.

### 0.3 How it is amended

A written proposal of the new/modified principle with its justification, approved by
the team. Rule: **every clause aspires to the most mechanical rung of the enforcement
ladder** — if it can become a linter rule, structural test, or CI gate, it is
converted, and the check replaces the prose. A clause without mechanical enforcement is
a candidate to become one, not an end in itself.

### 0.4 What happens when a principle is violated

Any deliberate deviation is recorded as an **ADR** explaining why this case justifies
the exception. The exception does not become the rule; each future case is justified
anew. ADRs live in the TRD's ADR section when a TRD exists, and as files in
`docs/adrs/ADR-NNN-<slug>.md` otherwise (or when the decision deserves its own file).

---

## 1. Hexagonal architecture (the default for software products)

### 1.1 The idea

Without explicit architecture, business logic tangles with technical detail: a domain
rule ends up encoded in a prompt, a severity decision lives inside a SQL query, the
code that decides behavior imports a vendor SDK. Hexagonal architecture — Cockburn's
**Ports and Adapters** — solves this with one idea: the problem domain lives isolated
from the outside world, connected only through explicit interfaces.

### 1.2 The dependency rule

> **Dependencies always point inward: from the outside in, never the reverse.**

This is the only rule that truly must be defended. Everything else — how many layers,
their names, where DTOs live — is derived preference.

- The **domain** imports nothing from the application, infrastructure, frameworks, or
  I/O libraries. Only the stdlib and pure computation libraries.
- The **application** imports from the domain (plus the bounded framework exception of
  §2, if declared). Nothing else from outside: no model SDKs, no DB drivers, no HTTP
  clients.
- The **infrastructure** imports from application and domain. It is the only layer
  that knows external SDKs.

A reversed import is a layer error. Enforce with a structural linter in CI
(**import-linter**, `layers` + `forbidden` contracts in `pyproject.toml`, run as
`lint-imports` in the validation gate) whose error message teaches the remediation.

### 1.3 The layers

- **Domain.** Pure model of the business: entities, value objects, aggregates, domain
  events, domain services, business exceptions, invariants. Everything expressible
  without I/O (or an LLM) lives here. Zero framework imports.
- **Application.** Use cases / orchestration: thin coordinators that read state,
  execute domain operations, talk to the outside via ports, and return results.
- **Ports.** The interfaces the application declares to talk to the outside. Anything
  that leaves the process (DB, LLM, external API, storage) goes through a port.
- **Infrastructure (adapters).** Concrete implementations; the only pieces importing
  external SDKs. Swapping an adapter touches neither domain nor application.

Ports live in the **application layer** (Cockburn) — recorded in TRD ADR-001. Changing
it requires another ADR.

### 1.4 When NOT to apply layers

KISS beats architecture. Health endpoints, flat read-only projections, one-off
scripts — go direct. The separating question: **does this have business invariants
that can break?** Yes → hexagonal. No → direct, with one line of why.

In this repo: `GET /health` goes direct; evaluation scripts under `scripts/` go direct.
Extraction and RAG have invariants (every page OCR'd, boxes in PDF points, one box per
occurrence, unique chunk IDs, sources ⊆ retrieved) → hexagonal.

---

## 2. Opinionated frameworks × hexagonal — how they coexist

Frameworks with strong opinions create tension with "the business knows no
frameworks". **The answer is never to abandon the architecture — it is to resolve the
tension explicitly**, once, in writing. The stack's only opinionated framework is
**FastAPI** (with its companion **Pydantic**). Everything else — Tesseract, PyMuPDF,
spaCy, sentence-transformers, Chroma, the openai SDK — is a library, and libraries live
in infrastructure behind ports (§4). Resolution recorded in
[ADR-012](docs/adrs/ADR-012-fastapi-pydantic-layering.md).

### 2.1 FastAPI + Pydantic

1. **Which layer does the framework's primitive occupy?** FastAPI is a **driving
   adapter**. Routers, `Depends`, `UploadFile`, exception handlers, middleware and the
   lifespan composition root all live in `app/api/` (and `app/main.py`). FastAPI does
   **not** own the application layer: use cases are plain classes invoked by routers.
2. **What exactly may the application import from it?** **Nothing.** No exception is
   declared — domain and application import neither `fastapi` nor `pydantic`. Domain
   types are stdlib `dataclass(frozen=True, slots=True)` / `enum`; ports are
   `typing.Protocol`.
3. **What stays out of the framework?** Upload validation rules (magic bytes, size,
   page limits) are plain functions/classes the router calls; business rules (name
   normalization, matching threshold, alignment, chunking) are domain code. HTTP status
   mapping is the only "logic" in the API layer, and it is a lookup table from domain/
   infrastructure error types.
4. **Piece-to-layer mapping:**

| Piece | Layer | Notes |
|---|---|---|
| `APIRouter`, path operations, `Depends`, `UploadFile`, `Form` | api (driving adapter) | Routers stay thin: parse → call use case → map result to DTO |
| `app/models/schemas.py` (Pydantic) | api (driving adapter) | Fixed HTTP contract (PRD); mapped to/from domain types at the router edge |
| Exception handlers → HTTP status | api | Domain/infra error type → status code table |
| Lifespan + dependency providers | api / `app/main.py` | **Composition root**: the only place adapters are instantiated and injected |
| `pydantic-settings` `Settings` | infrastructure | Read once at startup; values injected into adapters — never imported by domain/application |
| Domain entities / value objects | domain | stdlib dataclasses + enums; pure computation libs allowed (e.g. `rapidfuzz`) |
| Use cases, ports (`Protocol`) | application | Depend only on domain types |
| Tesseract, PyMuPDF, spaCy, sentence-transformers, Chroma, openai SDK | infrastructure | One adapter per port; vendor exceptions translated at the edge (§8) |

Steps stay thin: read input → call domain and ports → return result. If a router or
use case grows business `if`s, that logic moves to the domain.

---

## 3. Bounded contexts

A bounded context (DDD) is a portion of the domain model sharing internal language and
rules, communicating with other BCs through explicit contracts. Preference order:
**domain events** → **contracts consumed via port** → **direct cross-BC call**
(exception, recorded as ADR). Package structure mirrors BC structure. The definitive BC
list emerges with the code — record it as an ADR, don't invent it up front.

## 4. Ports as Strategy done right

Ports and adapters ARE the Strategy pattern at architectural scale. Design rules:

1. **Small interface.** One port covers one cohesive responsibility. Fifteen methods =
   several ports in one.
2. **Domain types in the signature.** Never types from the external lib — a port
   exposing vendor types is not swappable (no `fitz.Page`, `spacy.tokens.Span`,
   `numpy.ndarray`, Chroma result dicts in a port signature).
3. **Domain errors at the translation edge.** The application handles
   `VectorStoreUnavailable`, not the vendor's exception (§8, *Translation at the
   adapter edge*).
4. **No shared state between calls.**
5. **Injected, never imported.** Use cases receive their ports through the
   constructor; adapters receive their configuration through the constructor. Concrete
   adapters are instantiated in exactly one place — the composition root (`app/main.py`
   lifespan) — and handed to routers via FastAPI dependency providers. No module-level
   instances, no `get_x()` global getters, no service locator. Heavy resources (models,
   clients) are loaded once at startup, never per request.

When ports meet these, the system satisfies Liskov Substitution at its boundaries.

## 5. Curated pattern catalog

The pattern serves the design, not the reverse. A three-line pure function that solves
the case IS the answer. A pattern enters when there is real variability with more than
one live implementation, the piece changes for a different reason than its module, or a
test becomes grotesque without inverting the dependency.

- **Repository** — persistence of an aggregate behind an in-memory-collection
  interface. Not for flat read queries (a Query is more honest).
- **Unit of Work** — atomic operations across aggregates without the app knowing the
  ORM session. Not when one aggregate suffices.
- **Strategy** — see §4. Not with a single implementation and none on the horizon.
- **Specification** — composable, deterministic business predicates used in multiple
  places. Not for a trivial one-site validation: an `if` is sometimes the best
  specification.
- **Domain Events** — facts that happened, accumulated in the aggregate, published
  post-commit. Not when the effect must be in the same transaction.
- **Factory** — construction with complex invariants or several modes. Never wrap an
  honest constructor.
- **Command / Query** — light CQRS split. Not for trivial writes.
- **Pipeline** — step sequences inside an adapter (ingest: normalize → paginate →
  parse). Never competing with the macro orchestrator (§2).
- **Not patterns here:** Singleton (a module already is one), GoF Decorator
  (`@decorator`/HOF suffices), fluent Builder (defaults do it), global Service Locator
  (anti-pattern — inject via constructor).

## 6. Programming principles (heuristics, not laws)

Each principle solves one problem and creates another. The right question is never
"what does the principle say?" but **"what evidence do I have to tilt the balance?"**

Three questions worth more than the names:
1. **Do I know this, or am I guessing?** YAGNI — if guessing, don't add it.
2. **What changes together, what changes apart?** SRP/DRY — what changes together
   lives together.
3. **Does the next reader understand this unexplained?** KISS.

- **KISS.** If you must explain the code, it isn't simple. In genuinely complex
  problems, simplicity is relative to the problem.
- **YAGNI.** No real use case **today** → don't build it. **100x exception:** YAGNI
  yields only when retrofit cost is ~100× doing it now (canonical example: `tenant_id`
  on every new table in a multi-tenant system). NOT YAGNI: strong types, domain tests,
  and the hexagonal foundations — they are what makes any change cheap.
- **DRY corrected.** DRY applies to **knowledge**, not lines. Two look-alike functions
  representing different rules are coincidence of form, not duplication. Rule of
  three: first write, second copy, third abstract. "Duplication is far cheaper than
  the wrong abstraction" (Metz).
- **SOLID adapted.** SRP: one reason to change ("and" in the description = two). OCP:
  via interfaces/composition, but speculative OCP is YAGNI dressed up. LSP: prefer
  composition; wanting Liskov usually means wanting an interface, not inheritance.
  ISP: small specific ports. DIP: IS the hexagonal dependency rule.
- **Make illegal states unrepresentable.** Enums over validated strings; discriminated
  unions over `string | null` with a comment. Types catch bugs before tests, at zero
  runtime cost. Mandatory on every contract/schema that crosses a boundary.
- **Compose Method.** Short functions, one abstraction level. Anti-symptom: 3
  indent levels or >30 lines. Anti-anti-symptom: two-line functions doing a dance.
- **Tell, Don't Ask.** `case.complete()` over reading and mutating state outside the
  aggregate. Exception: multi-aggregate reads are reasonable.
- **Configuration is data, not code.** Every value that differs between environments
  or that someone may tune — hosts, ports, URLs, model names, thresholds, DPI, limits,
  timeouts, retry counts — lives in one typed, environment-overridable `Settings`
  object with safe defaults, is documented in `.env.example`, and reaches the code by
  injection (§4.5). A literal of that kind in a module is a bug.

**When principles collide:** KISS beats OCP until the 3rd variant · types beat YAGNI
always · when in doubt between DRY and wrong abstraction, duplicate · KISS beats SRP in
the skeleton, SRP wins later · allow reads over forced Tell. Meta-rule: **when in
doubt, the principle producing simpler code today wins — comment the why.**

## 7. Testing strategy — two layers: deterministic and evals

The system has **two natures**: deterministic code and LLM behavior. Each has its
verification layer; the Definition of Done requires both:

- **Deterministic layer** — the pyramid, 100% green:
  1. *Unit/Domain*: invariants, value objects, business rules. No I/O, no mocks. Many.
  2. *Integration*: application/use cases with in-memory **fakes** of the ports. Medium.
  3. *Adapter/Contract*: adapters against the REAL dependency (the real Tesseract
     binary, the real spaCy model, a real Chroma instance — no mock standing in for the
     engine). Marked `integration`. Medium.
  4. *Acceptance*: the assembled system with fakes or cheap models, derived from the
     ticket's GWT criteria. Few.
  5. *E2E/Smoke*: the real app over HTTP on the sample PDFs (and `docker compose up` →
     `/health`). Very few.
- **ML/LLM layer (evals)** — one suite per model-backed capability (NER extraction, box
  location, RAG retrieval, RAG answer) against the golden set: deterministic graders
  where possible; LLM-as-judge only for the subjective, binary and calibrated against
  expert labels (measure TPR AND TNR). LLM answer evals measured as **pass^k**
  (consistency), not pass@1. Balance both directions (positive and negative cases).
  Every observed failure ⇒ a new eval task.

**Fakes, not mocks.** For ports, use fakes (in-memory implementations behaving like
the real thing). Mocks couple tests to internals and break on refactor. LLM calls get a
scripted fake at the model-client level; their behavior is verified in evals, not in
unit tests asserting exact output.

**Coverage is a diagnostic, not a goal.** 95% on trivial adapters with 30% on the
domain is silent failure. What matters is which part of the **domain** lacks tests.

**Anti-patterns:** mocking the domain · mocking the engine in adapter tests · tests
coupled to internal structure · unit-testing exact LLM output · shared state between
tests.

## 8. Error handling

- **Philosophy.** Failure is the norm (an LLM is the least reliable dependency of
  all). The system degrades with dignity; it doesn't fall over.
- **Exceptions by default; Result types** only when the error is part of the domain
  and the caller must handle it in types (expected, flow-branching results).
- **Hierarchy.** `DomainError` (violated business rules, invalid input) ·
  `ApplicationError` · `InfrastructureError` (adapter failure — including LLM output
  that breaks its schema: a contract violation, not a half-valid dict that travels on).
  Clear mapping at the edge: DomainError → 4xx, InfrastructureError → 5xx with
  request-id.
- **Translation at the adapter edge.** External-lib exceptions never leave the
  adapter; they are translated to domain/infra errors, with context, in one place.
- **Rich exceptions.** Structured context, specific type, no PII in the message.
- **Every call that leaves the process has a timeout** (LLM, vector-store server, any
  HTTP) taken from configuration. A call without a timeout is a hang waiting to happen.
- **Retry only for idempotent, transient errors**, with exponential backoff + jitter,
  via the platform's retry mechanism, not a hand-rolled loop. Irreversible effects
  must be idempotent. Circuit breakers only for cascading external dependencies.
- **Validate at the edge, by content.** Inputs are validated where they enter (driving
  adapter) before any work starts: file type by its bytes (magic number), never by
  extension or client-declared content type; empty and oversized payloads rejected
  early (size read with a cap, not after loading everything); request bodies validated
  against typed schemas. Each rejection is a specific `DomainError` → 4xx.
- **Resources are scoped.** Every file handle, temp file/dir, PDF document, or client
  session is opened in a context manager (`with` / `try/finally`) so it is released on
  every path, including errors. Prefer in-memory processing; when a temp file is
  unavoidable, it lives in a temp dir deleted by the same scope.
- **Untrusted input is data, never instruction.** Content ingested from outside (user
  documents, web text) must not alter agent behavior; injection defense is a code
  guardrail, not a prompt guardrail.

## 9. Observability

- **Two planes, no duplication:** agent/LLM traces → the tracing platform (Langfuse/
  OTel GenAI or equivalent); service logs/metrics → standard. Traces are
  observability, not the business source of truth — durable decisions live in state.
- **Structured logs** (JSON): `timestamp` UTC, `level`, `event` (a name, not free
  prose), `correlation_id`, tenant/user context where applicable. No DEBUG in prod.
- **Metrics:** RED per endpoint + domain metrics. Watch label cardinality: high-
  cardinality ids go in logs and traces, never in metric labels.
- **PII:** never in logs; redaction processor before emit; hashes/last-4/internal ids
  instead. In this product the extracted **person names and document text are PII**:
  log counts, document hashes and page indexes — never the names or the text.
- **Liveness ≠ readiness.** Confusing them causes cascade restarts.
- **Cost/latency per execution is a design constraint** for LLM systems — measure from
  day 1; raise to thresholds when there are real users.

## 10. Naming and ubiquitous language

- Infrastructure code, class/module names, and commits in English; domain terms with
  a proper name in the business language are **kept, not translated** (translating
  breaks the ubiquitous language with domain experts).
- **No empty suffixes** (`Manager`, `Handler`, `Util`, `Helper`, bare `Service`);
  meaningful suffixes yes (`Repository`, `Port`, `Adapter`).
- **Errors named by the violated rule**, not generic: `UploadIsNotPdf`,
  `UploadTooLarge`, not `ValidationError`.
- Only abbreviations the domain experts use. Heuristics: would a domain expert
  recognize this name? Does this suffix add information? Am I translating something
  that has a proper name?

## 11. Change workflow

- **Three change types:** observable behavior change → born from a ticket with
  verifiable GWT criteria tracing to PRD/TRD, plan approved before code (rite
  proportional to size: small bug = direct prompt) · long-term technical decision →
  **ADR** · internal refactor with no behavior change → no spec needed; code review
  yes.
- **ADR format (short Nygard):** status · date · context · decision · alternatives
  considered (never empty) · consequences (including the negative). Written **before**
  implementing; monotonic numbering; one ADR = one decision; decisions are not
  silently reopened — a new ADR supersedes.
- **TDD.** The failing test comes BEFORE the code. Evidence that something works is
  test/eval output, not assertions — human or agent.
- **Review.** Every merge to main passes review + green checks. The reviewer checks:
  layer separation, tests/evals at the right level, naming, no new libraries without
  an ADR, no unjustified `Any`/`type: ignore`, no orphan TODOs.
- **The single door.** Every finding (bug, idea, LLM failure, debt) enters through the
  issue tracker. What isn't versioned in the repo doesn't exist. A failure repeated
  twice → a rule at the most mechanical rung possible.

## 12. Universal negative list

Things we never do:

- Mix business logic with technical detail.
- Import vendor SDKs, DB drivers, or HTTP clients from domain or application (only
  infrastructure; §2 exceptions are named and bounded).
- Invert the dependency rule.
- Put critical guardrails only in prompts — irreversible controls are code.
- Mock the domain. Mock the engine in adapter tests.
- Let untyped dicts/objects cross a contract boundary.
- Use `Any` / `# type: ignore` without adjacent justification.
- Leave TODOs without name, date, and issue link.
- Add an external library without an ADR.
- Design for imagined needs (YAGNI). DRY on the first duplicate (rule of three).
- Pattern ceremony where a function suffices (KISS).
- Generic errors (`Exception`, `RuntimeError` are ways of not deciding).
- Silence errors (`try/except: pass`).
- Hardcode hosts, ports, model names, thresholds, DPI, limits, or timeouts (§6).
- Call anything outside the process without a timeout (§8).
- Trust a file extension or client-declared content type (§8).
- Open a file, temp file, or document outside a context manager (§8).
- Instantiate an adapter anywhere but the composition root (§4.5).
- Persist PII in logs.
- Public functions without a one-line docstring (the what and why; the signature
  already says the types).

## 13. How we say "no" as a team

**"Let's do it quick without a spec."** The rite is proportional, but a feature without
an approved plan violates the gate. Correcting a plan costs a sentence; a diff, 300
lines. · **"Mock it, it's easier than the real engine."** Not in adapter tests — the
discomfort of installing Tesseract is the price of tests that catch real bugs. · **"The
prompt already checks it."** A prompt is not a guardrail. Critical → code; LLM
behavior → eval with pass^k. · **"It goes against the principle but makes sense
here."** Possibly — with an ADR. The exception doesn't become the rule by habit. ·
**"Let's abstract it now, we'll surely need it."** YAGNI; the rule of three will call
you. · **"Put it in `shared/`."** The favorite dumping ground. If you doubt where it
goes, it probably belongs to a specific bounded context. · **"The plugin/skill says
X."** Skills are aids, not authority. This constitution and CLAUDE.md rule.

## 14. Known gaps (brownfield)

N/A — greenfield. The scaffold's stub modules (`app/services/*.py`, module-level
functions raising `NotImplementedError`) are placeholders to be replaced, not code to
migrate.

---

## 15. Closing

This constitution is a floor, not a ceiling. It describes the minimum that is not
renegotiated case by case. Anyone — human or agent — writing code here operates under
these principles, and every clause that can become a mechanical check will become a
mechanical check.
