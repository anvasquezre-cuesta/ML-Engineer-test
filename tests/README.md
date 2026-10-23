# Tests

Each correctness trap in the brief has a fast unit test with fakes, the real pipeline is proven once on the sample PDFs, and every HTTP error path is asserted end to end. Test names say which trap they guard.

## Layers

| Layer | Folder | Uses | Speed |
| --- | --- | --- | --- |
| Unit | `tests/unit` | Hand-written fakes from `tests/fakes.py`; pure functions; mocked HTTP for the LLM client | Milliseconds |
| End-to-end | `tests/e2e` | The real `create_app` and wiring (`app/container.py`'s shape) with fake adapters, through `TestClient` | Milliseconds |
| Integration | `tests/integration` (marker `integration`) | Real PyMuPDF, Tesseract, spaCy, sentence-transformers, Chroma and Ollama on `sample_pdfs/` | ~2 min |

Every integration test **skips cleanly** when its dependency is missing (no Tesseract, no spaCy model, no embedding model offline, no LLM endpoint), so `uv run pytest` passes on any machine and runs everything on a complete one.

```bash
uv run pytest -q                          # everything available on this machine
uv run pytest -q -m "not integration"     # fakes only: no Tesseract, models or Ollama needed
uv run pytest -q -m integration -rs       # only the real pipeline; -rs shows why anything skipped
uv run pytest --cov                       # branch coverage; the build fails below 90 %
```

**Fakes, not mocks.** `FakeRenderer`, `FakeOCR`, `FakeNER`, `FakeEmbedder`, `InMemoryVectorStore`, `FakeLLM` and `FailingStore` are tiny working implementations of the domain Protocols; they record their calls so tests can assert, for example, that the LLM was never called. `NameMatcher` and `Chunker` have no fakes: their real implementations are pure and fast. `unittest.mock` is not used; the LLM client is tested against a mocked HTTP transport (`httpx2.MockTransport`) instead.

## The traps from the brief, and the tests that guard them

| # | Trap | Tests |
| --- | --- | --- |
| 1 | Boxes in PDF points, not pixels | `unit/test_geometry.py::test_px_to_pt` (6 cases), `::test_box_conversion_scales_every_edge_without_flipping_y`; `integration/test_tesseract_ocr.py::test_known_word_lands_where_it_is_printed` ("Robert" at (60, 267) pt) |
| 2 | OCR every page, including the first | `unit/test_ocr_service.py::test_every_page_processed_including_first`; `integration/test_pymupdf_renderer.py::test_render_yields_every_page_in_order_with_sizes_in_points`; `integration/test_tesseract_ocr.py::test_every_page_of_a_two_page_scan_is_read` |
| 3 | Name → box mapping | `unit/test_name_extraction.py::test_entity_box_merges_overlapping_words_and_excludes_title` ("Dr. Aisha Patel"), `::test_hyphenated_surname_is_one_word_in_one_box`, `::test_partial_overlap_selects_the_whole_ocr_word` (`Foster):`), `::test_bullet_inside_the_entity_is_kept_out_of_the_box` |
| 4 | Headings merged across lines; ALL-CAPS headings | `unit/test_name_extraction.py::test_entity_crossing_lines_is_never_produced`, `::test_all_caps_heading_is_not_a_person` |
| 5 | Case- and accent-insensitive matching | `unit/test_fuzzy_matching.py::test_match_ignores_case_and_accents`, `::test_normalize_name` (9 cases), `::test_letters_nfkd_cannot_decompose_still_match` |
| 6 | OCR punctuation (apostrophes) | `unit/test_fuzzy_matching.py::test_apostrophe_names_match` (O'Brien ~ OBrien ~ O’Brien) |
| 7 | Full-string similarity, no substring trick | `unit/test_fuzzy_matching.py::test_partial_or_different_names_stay_below_threshold` (Jennifer vs Jennifer Liu, Robert vs James Chen) |
| 8 | Chunking never cuts a word | `unit/test_chunker.py::test_chunker_never_splits_words` (28 cases), `::test_overlap_between_neighbours_is_exact`, `::test_invalid_window_is_rejected` |
| 9 | A second ingest must not overwrite the first | `unit/test_ingestion_service.py::test_second_ingest_does_not_overwrite_first`, `::test_reingesting_the_same_file_changes_nothing`; `integration/test_vector_stores.py::test_two_documents_are_both_stored`, `::test_same_document_twice_leaves_the_count_unchanged`; `e2e/test_ingest_api.py::test_second_document_does_not_overwrite_the_first` |
| 10 | No hallucinated sources | `unit/test_ask_service.py::test_sources_come_only_from_retrieved_chunks`, `::test_model_declining_to_answer_clears_the_sources` |
| 11 | Grounded answers: no LLM call without evidence | `unit/test_ask_service.py::test_no_llm_call_below_similarity_threshold`, `::test_gate_uses_the_best_match_and_context_keeps_a_weaker_answer_page`; `e2e/test_ask_api.py::test_unanswerable_question_is_not_found_without_llm_call` |
| 12 | Reject non-PDFs by content, not extension | `unit/test_document_loader.py::test_rejects_non_pdf_by_content_not_name`; `e2e/test_errors.py` case "non-PDF by content" |
| 13 | Empty, oversized, malformed requests | `e2e/test_errors.py::test_error_path_returns_json_with_detail_and_request_id` (20 cases: every 4xx/5xx with `detail` + `request_id`); `unit/test_uploads.py` |
| 14 | Correct on the sample PDFs | `integration/test_golden_names.py::test_golden_names_on_sample_pdfs`: all 55 hand-labelled mentions (`fixtures/expected_names.json`) on the right page, no false positives, every box inside 612 × 792 pt |

## Beyond the traps

| Concern | Tests |
| --- | --- |
| Timeouts and retries on the LLM | `unit/test_openai_llm.py` (connection error, timeout, 3 attempts on 503, recovery after one 500, unknown model, readiness ping without retries) |
| Vector-store failures | `unit/test_chroma_store_errors.py` (startup, write, query, count → 503); `unit/test_qdrant_store_errors.py` (transient errors retried, client errors not, exhausted retries → 503) |
| One store contract, two implementations | `integration/test_vector_stores.py`: every test parametrised over Chroma and Qdrant (in-process), persistence on disk for both |
| Upsert-then-prune, persistence | `integration/test_vector_stores.py::test_reingest_with_fewer_chunks_prunes_the_stale_ones`, `::test_data_survives_a_restart` |
| Embedding truncation is visible | `integration/test_sentence_embedder.py::test_truncation_is_logged` |
| Request IDs and privacy in logs | `e2e/test_observability.py` (every line of a request carries its ID; no names), `unit/*::*_never_names`, `e2e/test_errors.py::test_validation_errors_do_not_echo_the_rejected_input` |
| Liveness vs readiness | `e2e/test_health.py`, `unit/test_readiness.py` |
| Fixed API contract (no renames, only optional additions) | `unit/test_schema_contract.py` against `fixtures/original_contract_schema.json`, the skeleton's schemas frozen from commit 7acb727 |
| Configuration | `unit/test_config.py` (env overrides, validation, secret not in repr) |
| Audit viewer | `e2e/test_viewer.py` (served, wired to `/api/extract`, pinned pdf.js, no `innerHTML`); rendering checked in headless Chromium: 55 boxes on the names at 100 % and 200 % |
| The whole path | `e2e/test_ask_api.py::test_extract_ingest_ask_end_to_end` (fakes); `integration/test_extract_api_real.py`, `integration/test_ask_real.py` (real services, Gate B) |
