# Decisions

Short notes on the choices that shaped this implementation, and the trade-offs behind
them. Bullets are grouped by area.

## Contract and shape

- `app/models/schemas.py` is untouched. No optional fields were added.
- The skeleton's function signatures (`find_name_bounding_boxes(pdf_path, text)` and so
  on) implied re-reading the PDF in every service. I OCR once, produce a list of pages
  with word boxes, and pass that object to NER and bbox lookup instead.
- Bounding boxes use a top-left origin with y growing downward, in PDF points. That is
  what PyMuPDF and pdf.js both use, so the viewer is a plain scale multiply. Classic PDF
  user space is bottom-left; a consumer that needs it converts with
  `y' = page_height - y - height`.
- The pixel to point scale comes from `page.rect / pixmap size` rather than `72 / dpi`,
  so a rotated or non-letter page still maps back correctly.

## Extraction

- OCR words keep Tesseract's `(block, paragraph, line)`. The locator only accepts a run
  of words that sits on one line or wraps once to the next line. That is what stops
  "John" on line 3 and "Smith" on line 9 from becoming one box.
- Token matching uses a fuzzy ratio (default 0.80) so `Gonza1ez` still matches
  `Gonzalez`. The name-level match against the request list uses a stricter 0.90.
- `fuzz.ratio` on the whole string, not `partial_ratio`. The partial version scores
  "Ann" against "Annabelle Smith" as a perfect match, which is the wrong answer for a
  compliance check. I also try "Last First" order and keep the better score.
- Normalisation strips accents (NFKD then drop combining marks), casefolds, and removes
  apostrophes and hyphens instead of turning them into spaces. The first version split
  "O'Brien" into two tokens while Tesseract emits one word, and Kevin O'Brien was never
  located. The sample PDFs caught it; the fakes did not.
- Single-token NER hits are dropped (`MIN_NAME_TOKENS=2`). On the samples the only
  single-token "person" was a project called Atlas. A real single-name person is rare in
  compliance documents; the setting exists if that assumption is wrong.
- Only names that were located on a page take part in fuzzy matching. A name with no
  location is not auditable, which is the whole point of the exercise, so I log it and
  leave it out rather than return it without a box.
- Names are deduplicated across the document by their normalised form but every
  occurrence gets its own box. Richard Hernandez appears five times in the minutes and
  the response has five entries.

## RAG

- Chunks are packed greedily by word up to `CHUNK_SIZE` characters with `CHUNK_OVERLAP`
  characters of trailing words repeated. Words are never split. Chunks never cross a
  page so every source can name the page a reviewer should open.
- Vector ids are `{uuid}:{chunk_index}` minted per ingest. A content hash would make
  re-ingest idempotent, which sounds nicer, but Chroma silently drops a reused id (there
  is a test that shows this), so an idempotent scheme would make a second upload vanish
  without any signal. The hash goes into the source string instead so duplicates are
  visible.
- `sources` are built from the retrieved chunks' metadata, never parsed out of the model
  output. The model is told to answer only from context and to say it does not know
  otherwise. With an empty store the service answers a fixed sentence and does not call
  the LLM at all.
- Embeddings are computed by the service and handed to Chroma so Chroma never downloads
  its own default embedding model on first use.
- The LLM client speaks the OpenAI chat-completions protocol. I tested it against
  OpenAI's shape in unit tests and against a self-hosted Qwen3.8 27B FP8 on vLLM for the
  end-to-end runs. Qwen writes its reasoning into `content` by default, so there is an
  `LLM_EXTRA_BODY` setting that merges arbitrary JSON into the request; setting
  `{"chat_template_kwargs": {"enable_thinking": false}}` fixes it without touching the
  server. That is configuration rather than string surgery on the answer.
- Retries use tenacity with exponential backoff on timeouts, connection errors, 429 and
  5xx. A 401 is not retried. The first real call through a Tailscale relay hit two read
  timeouts and succeeded on the third attempt, which was a useful accidental test.

## Engineering practices

- One flat `Settings` class with `pydantic-settings`; every knob is an env var and
  `.env.example` lists them all.
- Logs are JSON lines with a request id from a contextvar. The id is echoed in the
  `x-request-id` response header and in the 500 body so a user can quote it.
- Uploads are read in 1 MB pieces with a running size check so an oversized file is
  rejected before it is fully in memory. PDFs are detected by the `%PDF-` magic bytes,
  not the extension.
- No temp files anywhere: PyMuPDF opens from bytes and pixmaps go straight to PIL.
- OCR, NER, embeddings, and the Chroma query all run in a thread pool so the event loop
  is free while they work.
- A first version logged `extra={"name": ...}`, which collides with a reserved field on
  `LogRecord` and raised inside the warning path. Every two-page PDF returned a bare 500.
  Fixed, tested, and it is why there is now a JSON handler for unexpected errors.

## Docker

- `python:3.12-slim` plus Tesseract and the English and Spanish packs. uv installs from
  the lock file; the spaCy models are pinned wheels in `pyproject.toml` so there is no
  separate download step anywhere.
- CPU-only torch from the PyTorch index. The default wheel adds about 2 GB of CUDA
  libraries the service never uses. The image is still 3.2 GB, mostly torch (770 MB),
  spaCy, transformers, scipy, and two things Chroma drags in that I would trim next: the
  kubernetes client and onnxruntime.
- The embedding model is downloaded at build time into the image and `HF_HUB_OFFLINE=1`
  is set, so the container never reaches the internet at runtime.
- The first Dockerfile ended with `chown -R svc:svc /app`, which rewrote the whole venv
  into a new layer and took minutes. Now the app files are copied with `--chown` and
  only the data directory is made writable.

## Tests

- 65 tests. Unit tests cover each item the README says is graded: every page including
  the first, pixel to point scaling, word-safe chunking, accent and case folding,
  full-string versus substring scoring, grounded sources, unique ids across ingests,
  retry and no-retry paths on the LLM client, and upload validation.
- The API is tested end to end through `TestClient` with fakes for OCR, NER, embeddings,
  the store, and the LLM. One test runs the real models on `meeting_minutes.pdf` and
  asserts names on both pages with boxes inside the page; it skips when Tesseract is
  not installed.
- The vector store test uses a real embedded Chroma in a temp directory.

## Known limits

- Fuzzy matching at 0.90 lets "Aisha Patel" match "Aisha Patil". That is inherent to
  edit-distance matching on short strings; the threshold is a setting and the score is
  returned so a reviewer can see how close it was.
- spaCy sometimes tags an all-caps heading as a person. Those never locate (the locator
  wants consecutive matching words) and are dropped with a warning.
- Multi-language works through `OCR_LANGUAGES` and `NER_MODEL`; English and Spanish
  models ship in the image. Mixed-language documents are not handled specially.
- `/health` is a liveness probe only. A readiness probe that checks the store and the
  LLM would be the next addition.

## Use of AI tools

I used Claude Code throughout: to read the assignment and draft the implementation plan,
to write the first version of each module and test, to drive the Docker builds and the
verification runs against the sample PDFs, and to draft these documents. I reviewed and
edited every file, and the bugs listed above (the LogRecord collision, the apostrophe
split, the slow chown) were found by running the real pipeline and fixed with the
assistant's help. I authored every commit.
