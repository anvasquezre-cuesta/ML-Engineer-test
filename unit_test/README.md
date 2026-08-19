# Focused evaluation test suite

This directory is a deliberately small, high-signal subset of the broader
`tests/` suite. It maps directly to the correctness details called out in the
project README:

- OCR processes every page and converts image pixels to PDF points.
- NER returns only people while preserving occurrences and offsets.
- Bounding boxes cover complete names and do not join unrelated lines.
- Fuzzy matching handles case, accents, punctuation, and OCR noise while using
  full-name similarity.
- Uploads are validated by content, bounded in size, and always closed.
- Chunking preserves whole words and repeated ingestions cannot overwrite IDs.
- Transient vector-store failures are retried.
- The HTTP RAG path returns only verified, grounded source citations.

Heavy or external dependencies are replaced at their adapter boundaries (OCR,
spaCy, embeddings, PostgreSQL/pgvector, reranking, and the LLM). The production
orchestration and validation code still runs.

Run only this focused suite with:

```bash
uv run pytest unit_test -q
```
