# ADR-015 — Chunk by OCR layout blocks, sized in embedder tokens, no overlap

- **Status:** accepted
- **Date:** 2026-10-21
- **Related:** TRD ADR-011 (supersedes its sentence packing and overlap; "hand-rolled,
  pure, word-safe, page-bounded, in the domain" stays), ADR-009 (embedder whose
  tokenizer sizes the chunks), research `reports/Chunking y retrieval para RAG.md`

## Context

ADR-011 packed *sentences* up to `CHUNK_SIZE` characters with `CHUNK_OVERLAP`. Sentence
splitting on OCR text has to guess around `Dr.`, `10:05 AM.` and list items with no
final punctuation. Meanwhile the OCR already measures the document's layout for any
scanned PDF: Tesseract groups words into **blocks** (≈ paragraphs, list items, headings)
and our domain `Word` keeps that as `line_key = (block, paragraph, line)`.

The research found that simple structure-aware splitting matches or beats semantic /
LLM-based splitting, that ~200-token chunks without overlap are a strong default, and
that overlap scored worst on every metric but recall. It also flagged that e5 **silently
ignores everything past 512 tokens**: a chunk longer than that is stored but its tail
can never be found.

## Options considered

1. **Keep ADR-011** (sentence packing + overlap). Fragile sentence detection on OCR text;
   overlap creates near-duplicate candidates.
2. **One chunk per page.** Simple, but a dense page exceeds 512 tokens and gets
   truncated.
3. **Fixed token windows over the page text.** Simple, but ignores the layout the OCR
   already gives us and splits paragraphs arbitrarily.
4. **Pack OCR blocks up to a token budget** (chosen).

## Decision

Option 4, as a pure domain function over one document's OCR `Page`s:

- **Unit = OCR block**, in reading order.
- **Packing:** consecutive blocks of the same page are packed greedily while the chunk
  stays ≤ `CHUNK_MAX_TOKENS` (default 250). **No overlap.** Chunks never span pages, so a
  source is always exactly one page.
- **Only logical units, largest first:** paragraph (OCR block) → sentence → word. The
  same packing rule applies at every level: units are added whole, and **a unit that
  does not fit moves whole to the next chunk — it is never split in half**.
  - A block larger than the budget on its own is packed **sentence by sentence**. A
    sentence ends at a word ending in `.`, `?` or `!`, unless that word is a known
    honorific (`Dr.`, `Prof.`, … — the domain's existing honorific list).
  - Only a single sentence larger than the budget on its own (~180 words) is packed word
    by word. Words are atomic OCR tokens, so **no chunk can cut a word**.
  - Visual lines are never used as split points: a line break is where the page ran out
    of width, not where an idea ends.
- **Size is counted in the embedder's own tokens.** The chunker receives a
  `count_tokens(text) -> int` function (exposed by the `Embedder` port, implemented with
  the model's tokenizer), so the domain stays pure and the budget is exact for any
  language. `Settings` rejects `CHUNK_MAX_TOKENS` ≥ the model's 512-token window.
- **Metadata per chunk:** `document_id`, `file_name`, `page`, `chunk_index`.

No document-specific rules: no heading detection, no keyword lists, no thresholds tuned
to the sample PDFs.

## Consequences

- ➕ Works on any scanned document the OCR can segment; uses layout instead of guessing
  sentences.
- ➕ Pure and property-testable: concatenating a document's chunks reproduces its page
  texts (no word lost, duplicated or split); no chunk exceeds the budget except a single
  over-long word.
- ➕ No truncation by construction; no duplicate candidates; page-exact citations.
- ➖ Short documents give few chunks (the samples: about one per page). That is the
  honest result for short documents, not a defect.
- ➖ Relies on the OCR engine reporting block boundaries (already part of the `Word`
  contract).
- ➕ A sentence is split only when it alone exceeds the budget (~180 words) — vanishingly
  rare in business documents.
- ➖ Sentence ends are detected by final punctuation; an abbreviation outside the
  honorific list (`a.m.`, `Inc.`) is a false sentence end. It only matters inside a
  paragraph that already exceeds the budget, and then only if the chunk closes exactly
  there — accepted for simplicity.
- ➖ A heading can end up as the last block of one chunk while its section starts the
  next; accepted for simplicity — the 250-token budget makes it rare.
