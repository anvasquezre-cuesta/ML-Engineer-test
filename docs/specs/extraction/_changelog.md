# Changelog — extraction

## 2026-10-21 — Implementation
- T-001…T-007 implemented, one commit each (see `_manifest.md`), full gate green per
  ticket; evals: `eval_ner.py` P 1.000 / R 0.982, `eval_boxes.py` 54/54 boxes, recall 0.982.
- Divergences from the plan (recorded as amendments in `.claude/plans/extraction-epic.md`;
  ticket acceptance criteria unchanged):
  - T-001: `Container` holds no `Settings` (api must not import infrastructure); settings
    load through `load_settings()`, whose error names the `DOCINTEL_*` variable.
  - T-004: S1 picked `en_core_web_lg`, not `trf` — `sm` met P/R but leaked `Atlas`/`Forbes`
    (TRD §1 zero-leak criterion); `lg` passes without torch. ADR-013.
  - T-005: occurrences ordered by page-text offset (reading order); wrapped names have
    whitespace collapsed.
  - T-006: response coordinates rounded to 0.01 pt.

## 2026-10-21 — Approval
- Approved by the human gate (Pablo): T-001…T-007.

## 2026-10-21 — Initial generation
- Created T-001…T-007 from `README.md` (PRD) + `docs/trds/document-intelligence-trd.md` v0.1
  (as read on 2026-10-21), scoped to TRD §14 phases P0 and P1. All pending-approval.
