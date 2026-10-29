# Cut OCR pages into word-safe, token-bounded chunks

## Metadata
- **ID**: T-001 · **Version**: v1 · **State**: approved
- **Traces to**: PRD objective(s) O6, O4 · TRD section(s) §2 (Ingest flow), §3 (Chunker), ADR-011, ADR-015
- **Depends on**: none · **Wave**: 1
- **Files likely touched**: `app/domain/` (new chunking module, `Chunk` entity), `tests/unit/domain/`
- **Design**: skip (algorithm fixed by ADR-015; pure function, no new boundary)

## Goal
Turn a document's OCR pages into the chunks that RAG will embed and search, so that no
chunk ever cuts a word, none exceeds the embedder's token budget, and every chunk can be
cited to exactly one page — for any scanned document, not just the samples.

## User Story
As the ingestion pipeline
I want a document's OCR pages split into page-bounded chunks that respect the layout the OCR measured
So that every chunk is fully searchable by the embedder and every answer can cite an exact page

## Functional Description
- Input: the OCR `Page`s of one document (words in reading order, each with `line_key = (block, paragraph, line)`), the document id, the file name, a token budget `max_tokens`, and a `count_tokens(text) -> int` function. Output: an ordered sequence of `Chunk`s with `document_id`, `file_name`, `page` (0-based), `chunk_index` (0-based, consecutive across the whole document) and `text`.
- **Unit = OCR block** (same `line_key[0]`) in reading order. Words inside a line are joined by one space, lines by a newline, blocks by a newline — the same convention as `build_page_text`.
- **Packing:** consecutive blocks of the same page are added to the current chunk while `count_tokens(chunk text) ≤ max_tokens`. A block that would overflow starts a new chunk. **No overlap.** Chunks never span pages.
- **Only logical units, largest first: paragraph (OCR block) → sentence → word.** At every level the rule is the same: units are added whole, and a unit that does not fit closes the current chunk and moves **whole** to the next one — never split in half.
- **Oversized block** (alone > `max_tokens`): packed sentence by sentence. A sentence ends at a word ending in `.`, `?` or `!`, unless that word is in the domain's existing honorific list (`Dr.`, `Prof.`, …).
- **Oversized sentence** (alone > `max_tokens`): packed word by word. A single word over budget becomes its own chunk (never split).
- Visual lines are never split points.
- A page with no words produces no chunks; a document with no words produces an empty sequence (not an error).
- No document-specific rules: no heading detection, no keyword lists.
- The function is pure: no I/O, no logging, no imports outside the domain.

## Main Flow
1. Ingestion passes the OCR pages of a 2-page document, a budget of 250 and a token counter.
2. The chunker walks each page's blocks in reading order, packing them under the budget.
3. It returns chunks numbered 0..n-1, each tagged with its page.

## Alternative Flows
- **Empty page**: Given a page with zero words → it contributes no chunk; numbering stays consecutive.
- **Empty document**: Given pages with no words at all → an empty sequence is returned.
- **Block larger than the budget**: Given a block whose text counts more than `max_tokens` → it is packed sentence by sentence; no sentence is split unless it alone exceeds the budget.
- **Sentence larger than the budget**: Given one sentence counting more than `max_tokens` → it is packed word by word.
- **Word larger than the budget**: Given one word whose own count exceeds `max_tokens` → it is emitted alone as one chunk.
- **Invalid budget**: Given `max_tokens < 1` → `ValueError` (programming error, not a user error).

## Acceptance Criteria
1. **No word lost, duplicated or cut** *(property test: ≥ 200 seeded random documents in plain pytest — no new dependency)*
   - Given any generated set of pages (random words, blocks, lines; empty pages included)
   - When they are chunked with a whitespace token counter and any budget ≥ 1
   - Then the sequence of words across all chunks equals the sequence of OCR words, in order, and every chunk's text starts and ends on a whole word
2. **Budget respected**
   - Given the same generated input
   - When it is chunked
   - Then every chunk satisfies `count_tokens(text) ≤ max_tokens`, except a chunk consisting of exactly one word
3. **Page-bounded with exact metadata**
   - Given a 2-page document whose blocks would fit in one chunk if pages were merged
   - When it is chunked with a large budget
   - Then exactly one chunk per page is produced, `page` is 0 and 1, and `chunk_index` is 0 and 1
4. **Blocks are packed, not split, when they fit**
   - Given a page with three blocks of 40, 40 and 40 tokens and a budget of 100
   - When it is chunked
   - Then two chunks are produced: blocks 1+2, then block 3
5. **Oversized block split only between sentences**
   - Given one block of 4 sentences of 100, 120, 90 and 90 tokens, laid out so that line breaks fall mid-sentence, with `Dr. Foster` inside the first sentence, and a budget of 250
   - When it is chunked
   - Then exactly two chunks are produced — sentences 1+2, then 3+4 — every chunk ends on a sentence end, and `Dr.` is not treated as one

## Technical Notes *(only if applicable)*
- Domain code: no imports of `fastapi`, `pydantic`, `chromadb`, `sentence_transformers` or any vendor SDK — CONSTITUTION §1.2, enforced by `lint-imports`.
- `count_tokens` is injected so the domain never loads a tokenizer; the real one comes from the `Embedder` adapter in T-003 — ADR-015.

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
- [ ] The chunking module contains no string literal or regex that detects headings, titles or specific words.
- [ ] `uv run lint-imports` passes with the new module in `app/domain/`.
