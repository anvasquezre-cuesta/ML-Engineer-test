# Manifest — rag

- **Epic slug:** `rag`
- **Sources:** PRD `README.md` (commit `7acb727`) · TRD `docs/trds/document-intelligence-trd.md` v0.1 + RAG revisions of 2026-10-21 (uncommitted) · ADR-014, ADR-015 (2026-10-21) · `CONSTITUTION.md` v1.0
- **Jira epic:** — (local-first; no tracker)

| ID | Title | State | Version | PRD objectives | TRD sections | Depends on | Jira | Last CR | Implemented in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-001 | Cut OCR pages into word-safe, token-bounded chunks | approved | v1 | O6, O4 | §2, §3, ADR-011, ADR-015 | none | — | — | `085e702` |
| T-002 | Rank chunks by exact terms (BM25) | approved | v1 | O7, O4 | §3, ADR-014, ADR-005 | none | — | — | `3d44d11` |
| T-003 | `POST /api/ingest` end to end | approved | v1 | O6, O3, O4 | §2, §7, §8, §10, ADR-007, ADR-008, ADR-009, ADR-015 | T-001 | — | — | `234839f` |
| T-004 | Rerank (question, chunk) pairs with a cross-encoder (spike S6) | approved | v2 | O7, O4 | §3, §8.2, §12, §15, ADR-014 | T-003 | — | CR-001 | `fbcd85c` |
| T-005 | Retrieve the most relevant chunks for any question, with a relevance gate | approved | v1 | O7, O4 | §1, §2, §10, §11, ADR-014 | T-002, T-003, T-004 | — | — | `397a5e1` |
| T-006 | `POST /api/ask` end to end with cited, code-built sources | approved | v1 | O7, O3, O4 | §1, §2, §5, §9, §10, §11, §12, ADR-006, ADR-010 | T-005 | — | — | `f3ac52f` |
