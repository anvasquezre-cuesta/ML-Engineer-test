# ADR-014 — Hybrid retrieval (dense ∪ BM25) + cross-encoder rerank

- **Status:** accepted
- **Date:** 2026-10-21
- **Related:** TRD ADR-008 (Chroma stays the store; dense-only retrieval is superseded),
  ADR-009 (embedder), ADR-006 (gate and sources are code), ADR-015 (chunks), research
  `reports/Chunking y retrieval para RAG.md`

## Context

The TRD planned dense-only retrieval: embed the question → Chroma top-k → similarity
gate. Two problems:

- **Dense retrieval is weak on exact terms** — names, codes, figures — which compliance
  documents are full of. On entity questions BM25 found the answer in the top 20 72 % of
  the time vs 50–57 % for dense retrievers (Sciavolino et al., 2021). Anthropic's
  contextual-retrieval study measured dense + BM25 plus a reranker cutting retrieval
  failures by 67 %.
- **e5 cosine similarities sit in a narrow 0.7–1.0 band**, so a similarity threshold
  cannot tell relevant from irrelevant; the "not found" gate needs a better score.

Chroma's embedded mode has no lexical/hybrid search (that is a Chroma Cloud feature).

## Options considered

1. **Dense only** (current TRD). Weak on exact terms; no usable gate score.
2. **Dense + BM25 fused with RRF, no reranker.** Better recall, still no usable gate
   score.
3. **Dense ∪ BM25 candidates, then a cross-encoder reranker** (chosen). With a reranker
   reordering everything, rank fusion (RRF) adds nothing: the union of both candidate
   lists is enough.
4. **A store with native hybrid** (Qdrant sparse vectors, OpenSearch). Right at scale;
   a second system for a small corpus.

## Decision

Option 3. Every number is in `Settings`:

1. **Dense:** embed the question → top `RETRIEVAL_CANDIDATES` (default 10) from Chroma.
2. **Lexical:** BM25 (Okapi, k1 = 1.5, b = 0.75), a **pure domain function** over the
   stored chunks, tokenized with the existing ADR-005 normalizer (casefold, accent strip,
   punctuation collapse) → top `RETRIEVAL_CANDIDATES`. The chunks are read through the
   `VectorStore` port at query time: **no index lives in the process**, so there is
   nothing to rebuild at startup or keep in sync after an ingest. No new library.
3. **Rerank** the de-duplicated union (≤ 20 chunks) with a cross-encoder behind a new
   `Reranker` port; keep the best `TOP_K` (default 5), best first.
4. ~~**Relevance gate:** best rerank score below `RERANK_MIN_SCORE` ⇒ deterministic "not
   found in the ingested documents", no LLM call.~~ **Removed by CR-002 (2026-10-21):**
   "Who wrote the memo?" scores −6.47, below an unanswerable question (−4.49), so no
   threshold separates them; the top-k passages always go to the LLM, which replies
   "not found" when they don't answer (pass^3 15/15). History of the original gate: The threshold is calibrated on the RAG
   golden set (answerable vs unanswerable questions). *Calibrated 2026-10-21
   (`scripts/eval_retrieval.py`, mmarco, 13 golden questions):* unanswerable top scores
   ≤ −4.49, answerable ≥ −0.70 (the NSF-grant figure question) → **`RERANK_MIN_SCORE =
   −2.59`** (midpoint). hit@5 10/10 and hit@1 10/10 — but the 3 samples yield only 5
   chunks, so top-5 holds everything; hit@1 is the meaningful number here.

**Reranker model: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`** — multilingual like
our embedder (ADR-009), loaded with sentence-transformers' `CrossEncoder`
(sentence-transformers is the runtime that loads the model, already chosen in ADR-009 —
no new dependency). Model name from config (`RERANKER_MODEL`).

*Amended 2026-10-21 by spike S6 (CR-001 of the RAG epic):* the first choice was
`BAAI/bge-reranker-v2-m3`; measured on the dev box (CPU, torch 2.14.1+cpu, 8 threads,
sentence-transformers 6.2.0) scoring 20 (question, ~300-token passage) pairs, p50 of
repeated runs after warm-up:

| Model | Params | 20 pairs | 10 pairs | Multilingual | ES question orders correctly |
|---|---|---|---|---|---|
| `BAAI/bge-reranker-v2-m3` | 568 M | 21.1 s | — | yes | yes (0.006 vs 0.00002) |
| `BAAI/bge-reranker-base` | 278 M | 6.2 s | 3.1 s | no (EN/ZH) | yes (0.036 vs 0.0) |
| **`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`** | 118 M | **2.0 s** | **0.9 s** | **yes** | **yes (−0.97 vs −5.23)** |
| `cross-encoder/ms-marco-MiniLM-L6-v2` | 22 M | 0.7 s | 0.4 s | no | no (−11.03 vs −11.43) |

Both bge models break the ≤ 2 s budget by 3–10×; mmarco is the only multilingual model
inside it. **Re-measured with `scripts/time_reranker.py` (T-004, 2026-10-21, 20 pairs ×
250 tokens, 10 runs after warm-up):** mmarco load 4.1 s (cached), **p50 1.55 s, p95
1.67 s** — within budget. Its outputs are raw logits (no sigmoid); they only order the
candidates (no cut-off since CR-002). The owner authorized trading the bge model for speed; the reranker step
itself is mandatory.

## Consequences

- ➕ Exact-term matches and meaning matches both reach the reranker, which orders them
  so the LLM sees the best passages first. Its scores are not used as a relevance
  cut-off (CR-002): their scale does not separate answerable from unanswerable.
- ➕ No new library, no in-process index state.
- ➖ BM25 per query is O(chunks stored): fine for this service, wrong past ~10⁴ chunks.
  Scaling path (DESIGN.md): a store with native hybrid search behind the same
  `VectorStore` port.
- ➖ ~2 s per question on CPU at 20 candidates (~1 s at the default 10 + 10 union, which
  is usually smaller after de-duplication). A GPU or a hosted reranker would allow
  `bge-reranker-v2-m3` again — a config change; the reranker step stays.
- ➖ OCR noise (`0'Brien`) hurts BM25; the dense side and the reranker are the
  mitigation, measured on the golden set.
