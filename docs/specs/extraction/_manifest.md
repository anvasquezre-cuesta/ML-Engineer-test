# Manifest — extraction

- **Epic slug:** `extraction`
- **Sources:** PRD `README.md` (commit `7acb727`) · TRD `docs/trds/document-intelligence-trd.md` v0.1 (2026-10-21) · `CONSTITUTION.md` v1.0
- **Jira epic:** — (local-first; no tracker)

| ID | Title | State | Version | PRD objectives | TRD sections | Depends on | Jira | Last CR | Implemented in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T-001 | Walking skeleton: hexagonal service with health, config, logging and quality gate | approved | v1 | O3, O5 | §2, §8, §11, ADR-001 | none | — | — | `87af6ae` |
| T-002 | Match extracted names against requested names | approved | v1 | O2, O4 | §3, ADR-005 | T-001 | — | — | `00be7ca` |
| T-003 | OCR every page into words with boxes in PDF points | approved | v1 | O1, O3, O4 | §2, §10, ADR-002, ADR-003 | T-001 | — | — | `5233bae` |
| T-004 | Recognize person names and measure NER against a golden set (spike S1) | approved | v1 | O1, O4 | §1, §11, §15, ADR-004 | T-003 | — | — | `f3cd3ec` |
| T-005 | Locate every occurrence of a recognized name on its page | approved | v1 | O1, O4 | §2, ADR-004 | T-003 | — | — | `847b69b` |
| T-006 | `POST /api/extract` end to end | approved | v1 | O1, O2, O3, O4 | §1, §2, §3, §10, §11 | T-002, T-004, T-005 | — | — | `9c64ce2` |
| T-007 | Reject invalid uploads and malformed name lists on `/api/extract` | approved | v1 | O3, O4 | §9, §10 | T-006 | — | — | `42f90bc` |
