# Match extracted names against requested names

## Metadata
- **ID**: T-002 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O2, O4 · TRD section(s) §3, ADR-005; CONSTITUTION §6, §7
- **Depends on**: T-001 · **Wave**: 2
- **Files likely touched**: `app/domain/` (name normalization + matching), `tests/unit/domain/`
- **Design**: skip (ADR-005 already fixes the scorer, normalization and threshold source)

## Goal
Decide, deterministically, which extracted names correspond to which requested names,
tolerating case, accents and small OCR errors but not substring coincidences. This is
what lets a compliance reviewer confirm "the person on our list appears in this document".

## User Story
As a compliance reviewer
I want each extracted name compared against the people I asked about, with a similarity score
So that I can confirm a listed person appears in the document even when the scan spelled them slightly differently

## Functional Description
- Input: a list of extracted name strings and a list of requested names, each `first_name` + `last_name`; plus the threshold (0..1) from `Settings` (default 0.90).
- Normalization applied to both sides before scoring: casefold → Unicode NFKD with combining marks removed (`María` → `maria`) → honorifics removed (`dr`, `prof`, `mr`, `mrs`, `ms`, with or without trailing dot) → punctuation (including straight and curly apostrophes, hyphens, commas, dots) replaced by a single space → whitespace collapsed and trimmed.
- A requested name's comparison string is `"{first_name} {last_name}"`.
- Score = full-string similarity on the normalized strings (rapidfuzz `fuzz.ratio` / 100). Substring/partial/token-set scorers are not used. Token order variation (`"Gonzalez, Maria"` vs `"Maria Gonzalez"`) is matched by taking the max of `ratio` and `token_sort_ratio`.
- A pair is reported when `score ≥ threshold`. Each reported match carries the **original** (un-normalized) extracted name, the requested name as `"{first_name} {last_name}"`, and the score rounded to 4 decimals in 0..1.
- Duplicate extracted strings (same name appearing on several occurrences) are scored once; the result contains at most one entry per (extracted name, requested name) pair.
- Output order: score descending, then extracted name, then requested name (deterministic).
- Empty extracted list or empty requested list → empty result, no error.

## Main Flow
1. Use case passes extracted names `["Dr. María González", "Robert Chen"]` and requested `[{"first_name":"Maria","last_name":"Gonzalez"}]`.
2. Domain normalizes both sides (`maria gonzalez`).
3. Domain scores every unique pair and keeps those ≥ 0.90.
4. Result: one match (`"Dr. María González"` → `"Maria Gonzalez"`, score 1.0).

## Alternative Flows
- **OCR noise**: Given extracted `"Maria Gonza1ez"` and requested Maria Gonzalez → score ≥ 0.90 → reported.
- **Substring only**: Given extracted `"Ana"` and requested `Ana María Rodríguez` → score < 0.90 → not reported.
- **Different person, shared surname**: Given extracted `"James Chen"` and requested Robert Chen → not reported.
- **Threshold changed by config**: Given threshold 0.80 → pairs scoring 0.80–0.89 are now reported.

## Acceptance Criteria
1. **Accent and case insensitivity**
   - Given extracted `"MARÍA GONZÁLEZ"` and requested `Maria / Gonzalez`
   - When matching runs with threshold 0.90
   - Then one match is returned with score `1.0`
2. **Robust to OCR noise and honorifics**
   - Given extracted `"Dr. Maria Gonza1ez"` and `"Kevin O’Brien"` and requested `Maria / Gonzalez`, `Kevin / O'Brien`
   - When matching runs
   - Then both are matched with score ≥ 0.90
3. **No substring inflation**
   - Given extracted `"Ana"` and requested `Ana María / Rodríguez`
   - When matching runs
   - Then no match is returned
4. **Threshold is respected and configurable**
   - Given a golden table of pairs with known scores
   - When matching runs with threshold 0.90 and again with 0.80
   - Then exactly the pairs with score ≥ threshold are returned each time, all scores within [0, 1]
5. **Deterministic, deduplicated output**
   - Given extracted `["Robert Chen", "Robert Chen"]` and requested `Robert / Chen`
   - When matching runs twice
   - Then each run returns exactly one match and both runs return identical lists

## Technical Notes *(only if applicable)*
- Pure domain code: stdlib + `rapidfuzz` only; no I/O — CONSTITUTION §1.2.
- Golden pairs live in a versioned fixture so they double as the regression eval (100 % pass required) — TRD §11.

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
- [ ] `grep -rn "partial_ratio\|token_set_ratio\|WRatio\|unidecode\|thefuzz" app/` returns nothing.
- [ ] The threshold value is read from `Settings`, not a literal in the domain module.
