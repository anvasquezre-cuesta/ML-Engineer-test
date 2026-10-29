# ADR-013 — `en_core_web_lg` is the default NER model

- **Status:** accepted
- **Date:** 2026-10-21
- **Related:** TRD ADR-004 (supersedes only its model choice; offset alignment stays),
  TRD §1 (success criterion), TRD §15 S1, ticket T-004

## Context

ADR-004 picked spaCy `en_core_web_sm` and spike S1 had to confirm it on real OCR output.
TRD §1 requires PERSON precision and recall ≥ 0.90 **and zero ORG/GPE/DATE leaks** on the
golden set. `scripts/eval_ner.py` (5 sample pages, 55 labelled occurrences, 300 DPI
Tesseract text) measured on 2026-10-21:

| Model | Precision | Recall | Golden negatives reported | S1 |
|---|---|---|---|---|
| `en_core_web_sm` | 0.912 | 0.945 | `Atlas`, `Forbes` | fail (leaks) |
| `en_core_web_md` | 0.929 | 0.945 | `Atlas` | fail (leak) |
| `en_core_web_lg` | **1.000** | **0.982** | none | **pass** |

`sm` also reported upper-case headings (`DIRECTORS - MEETING MINUTES`, `RESEARCH
DEPARTMENT ANNUAL`) and `Breakthrough` as persons, and missed `Lucas Zimmermann`. The
single `lg` miss is one `Elizabeth Park` (the model reads it as a place).

Cost measured on the dev box: load 1.9 s (`sm` 0.5 s) once at startup; ~257 ms per
3 000-character page (`sm` ~220 ms); 425 MiB on disk (`sm` 15 MiB).

## Options considered

1. **Keep `sm` and add a post-filter** (stop-list of known non-persons, drop all-caps
   spans). Small, but a hand-curated list tuned to five pages is overfitting the golden
   set, and it would not fix the missed persons.
2. **`en_core_web_trf`** (the upgrade path named in S1). Needs `spacy-transformers` and
   torch (~GBs, slower on CPU, bigger Docker image — TRD S3). Not measured: `lg` already
   meets every threshold without it.
3. **`en_core_web_lg`** (chosen). Same pipeline and API as `sm`, no new library, only a
   larger model wheel.

## Decision

Option 3. `DOCINTEL_NER_MODEL` defaults to `en_core_web_lg`, installed as a pinned wheel
URL in `pyproject.toml` (replacing the `sm` wheel). The model stays configurable; the
eval script takes `--model` to re-run S1 for any candidate.

## Consequences

- ➕ S1 passes with margin (P 1.000, R 0.982, no leaks); no new Python library, no torch.
- ➕ Swapping back is a config change plus a wheel line.
- ➖ ~410 MiB more on disk / in the Docker image and ~1.4 s slower startup.
- ➖ Five pages is a small golden set: the numbers show `lg` fits these documents, not
  that it generalizes. Every observed miss must become a golden entry (TRD §11).
