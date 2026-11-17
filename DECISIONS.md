# Engineering decisions

- **Fixed API:** keep `app/models/schemas.py` unchanged. HTTP routes handle
  validation and error mapping; services own orchestration and accept injectable
  dependencies. OCR and NER use protocols, as do the RAG query dependencies.
- **CPU and reproducibility:** the container uses CPU-only PyTorch and the locked
  English spaCy model. The local `all-MiniLM-L6-v2` embedding model is pinned to
  revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` and its allowlisted files
  are SHA-256 verified. Model identity is deliberately fixed rather than freely
  configurable: changing it requires compatible hashes and a new collection or
  migration. CPU inference is slower and the reviewed environment was ARM64.
- **OCR and coordinates:** process every physical page and retain page-local word
  offsets. Return boxes in PDF points relative to the unrotated crop box; omit
  unsafe associations rather than invent locations. Orientation selection uses
  OCR confidence and can be wrong; arbitrary skew and multilingual quality are
  not guaranteed. Bounding boxes were reviewed by the user only for the example
  documented in [manual evidence](docs/MANUAL_TEST_LOG.md).
- **Responsiveness and limits:** supervised POSIX subprocesses isolate OCR, NER
  and embeddings from the event loop. Admission, queue sizes, deadlines, PDF
  bytes, pixels and comparison work are bounded per process. Cancellation does
  not abandon already-started work. Abrupt machine failure can still prevent
  cleanup; local limits are not global across replicas. A preliminary two-job OCR
  memory measurement is summarized in [test evidence](docs/TEST_LOG.md).
- **Name matching:** compare complete names with case/accent normalization and
  `thefuzz.ratio`, rather than substring matching. NER can miss people or label
  projects and headings as people. Exact repeated-name recovery is opt-in:
  `NER_NAME_RECOVERY_PASSES=0` bypasses it; levels 1–3 add progressively broader
  deterministic searches over existing OCR and safely located full-name seeds.
  Recovered candidates are not promoted into new seeds. The rules can improve
  recall but can propagate a wrong label or match a different person; the fixed
  response has no per-location recovery provenance. The user chose full-name
  candidates rather than attributing isolated first or last names to people.
- **Ingestion and retrieval:** preserve whole words and physical pages, use
  128-token chunks with up to 32-token overlap, and assign new IDs to every
  ingestion, including repeated PDFs. SQLite tracks attempt/page metadata, while
  Qdrant stores vectors and OCR fragments. A reserved manifest binds the dedicated
  collection to the model and ledger; retrieval only uses completed attempts.
  These token settings are a baseline, not a measured retrieval optimum.
- **Consistency and errors:** SQLite and Qdrant are not a distributed transaction.
  Cooperating processes share same-host POSIX locks; incompatible collections
  fail closed. Unknown write outcomes require scoped, explicit cleanup, never a
  blind write retry. Qdrant read retries are limited to classified transport and
  transient HTTP failures; invalid requests and programming errors are not
  retried. Provider, vector-store and timeout errors return distinct safe messages
  without logging documents, questions, keys or provider response bodies.
- **LLM and grounding:** generation defaults to disabled. Gemini or an
  OpenAI-compatible HTTPS service requires an explicit provider, key, model and
  external-data opt-in; there is no automatic fallback. LLM retries are bounded
  and do not repeat `429`, read/write timeouts or invalid outputs. Citation IDs
  and exact quotes must match retrieved fragments, but literal matching does
  **not** prove that a citation supports a claim. Prompt injection and semantic
  errors remain possible. The 25-case real synthetic run and subsequent untested
  prompt adjustment are recorded in [the evaluation](docs/EVALUACION_FUENTES_RAG.md).
- **Privacy and audit:** the service has no multi-tenant authorization and must
  not be exposed to untrusted users. A separate React/Nginx service calls
  `/api/extract` and renders the local PDF in the browser. The protected, bounded,
  expiring single-process preview is optional, not production access control or
  secure erasure. External providers receive the question and retrieved excerpts;
  privileged operators can inspect environment variables.
- **Use of AI:** OpenCode and language models, including GPT-6.1 Terra, supported
  planning, repetitive logical reviews and drafts of code and tests under the
  author's direction. The author reviewed results and remains responsible for
  decisions and understanding the code. Human observations, simulated checks and
  real provider calls are recorded separately; AI review is not human approval.
