# Design

This service reads scanned PDF files. It does two jobs:

1. **Find people's names.** It finds every person's name in a PDF, shows
   where each name is on the page, and checks the names against a list.
2. **Answer questions.** It saves the text of PDFs and later answers
   questions using only that text.

## The parts (component view)

- **API.** The front door. It takes requests over HTTP (built with
  FastAPI). It only checks the request, calls the right piece of work, and
  turns errors into clear replies. It holds no business rules.
- **Worker.** A second program that does slow work in the background. It
  takes jobs from a queue (a waiting line of tasks).
- **Core logic.** The rules of the service, such as how names are matched
  and how an answer is checked. It does not know about any outside tool.
- **Ports and adapters.** Each outside tool sits behind a small fixed
  interface (a "port"). The code that talks to the tool is an "adapter".
  The core logic only sees the port, so a tool can be swapped without
  touching the logic. The adapters are:
  - page renderer: PyMuPDF turns each PDF page into a picture;
  - OCR (reading text from a picture): Tesseract;
  - name finder (NER, "named entity recognition"): spaCy;
  - name matcher: rapidfuzz;
  - text splitter: LangChain;
  - embedding model (embeds text so that texts with a similar meaning end
    up close together): FastEmbed;
  - vector database (stores the embeddings and finds the closest ones):
    Qdrant;
  - language model (LLM, the AI that writes the answer): OpenAI or AWS
    Bedrock, through LangChain;
  - file storage: S3 (SeaweedFS in local development);
  - queue: RabbitMQ in local development, SQS on AWS;
  - job and name records: DynamoDB.
- **Wiring and settings.** One file reads the settings once and connects
  the parts. It is the only place that knows which real tool is used.
- **Viewer.** A small web page that shows a PDF and draws a box around each
  name found.

## How a request flows (sequence view)

**Find names (`POST /api/extract`)**
1. Check the upload is a real PDF (by its first bytes), not empty and not
   too big.
2. Turn every page into a picture at 300 dpi (dots per inch).
3. Read the words with OCR, with the position of each word.
4. Find the people's names in the text with spaCy.
5. Draw one box per name, in PDF points (1/72 of an inch), measured from
   the top-left corner of the page. Titles like "Dr." are left out.
6. Look again for full names that spaCy found once but missed elsewhere.
7. Compare each found name with the list sent in the request and give a
   score from 0 to 1.
8. Save the names and boxes, then reply.

**Save a document for questions (`POST /api/ingest`)**
1. Check the upload the same way.
2. If the same file (same name, same content) was saved before, stop.
3. Read every page with OCR.
4. Split the text into chunks (short parts) of about 800 characters. A
   chunk never cuts a word in half.
5. Embed each chunk in two ways: a dense embedding for meaning, and a
   sparse embedding for keywords.
6. Remove the old version of the document, if any, and store the new
   chunks and their embeddings in Qdrant.

**Ask a question (`POST /api/ask`)**
1. Embed the question the same two ways.
2. Find the 8 best chunks, mixing the meaning results and the keyword
   results.
3. If nothing is found, reply "I cannot answer this from the provided
   documents." without calling the AI.
4. Send the chunks and the question to the AI. The AI must use only the
   chunks and mark each fact with the number of its chunk.
5. Keep only the sources the AI marked, and only if they were really among
   the found chunks. If the AI refuses, return no sources.

**Background jobs (`POST /api/jobs/extract` or `/api/jobs/ingest`)**
1. The API saves the PDF in file storage, writes a job record and puts the
   job in the queue. It replies at once with a job id.
2. The worker takes the job, marks it as running and does the same work as
   above.
3. It saves the result and marks the job as done.
4. The caller checks `GET /api/jobs/{id}` to see the state and the result.

## Tools chosen and why

- **Qdrant instead of Chroma.** It runs as its own service that the API
  and worker share, and searches by meaning and keywords in one call.
- **FastEmbed instead of sentence-transformers.** It runs a small model
  without PyTorch, so the image is smaller and starts faster. The model is
  `bge-small-en-v1.5`.
- **rapidfuzz instead of thefuzz.** It keeps accents, gives exact scores,
  and has type hints. The score compares the whole name, in any word
  order, so "Lucas" does not match "Lucas Moreau".
- **spaCy large model instead of small.** In the tests it was the only
  model without heavy AI libraries that found the sample names with no
  wrong boxes, and it is as fast as the small one.
- **DynamoDB** for job records and saved names: no server to run and no
  table changes to manage.
- **RabbitMQ and SQS** for the queue: RabbitMQ in local development, SQS on AWS,
  same worker code.
- **S3** to pass uploaded PDFs and job results between API and worker.
- **LangChain** to talk to the AI, so OpenAI and Bedrock use the same code.
  The prompt text lives in files, not in the code.

## What can go wrong, and what the service does

- **Bad upload** (not a PDF, empty, too big): a clear error at once.
- **OCR is slow or breaks:** OCR has a time limit and returns a clear error.
- **Qdrant is down:** try again a few times, then reply 503 (not available)
  or 504 (too slow).
- **The AI is down or slow:** try again a few times, then reply 502 or 504.
- **The AI makes things up:** it may only use the found chunks; if the
  answer is not there it must say so. Sources can only come from the found
  chunks.
- **The worker crashes in the middle of a job:** the job has a time lease.
  When the lease runs out, a clean-up task puts the job back and it runs
  again.
- **A job always fails:** after a few tries it is moved aside to a "dead
  letter" list for a person to look at.
- **The same job arrives twice:** safe. A finished job is skipped, and the
  stored data uses fixed ids, so nothing is doubled.
- **An export is too big:** refused with a clear message asking to narrow
  it by document or name.
- **Slow first start on AWS Lambda:** loading the models takes about a
  minute, so a few copies are kept warm and ready.

Known weak spots:
- A password-protected PDF gives a general 500 error instead of a clear
  "cannot read this file" error.
- The name finder is not perfect: it misses the name "Björn" in one sample.
- The request logging layer could be rewritten in a lighter, faster style.
- On AWS, Qdrant keeps its data on its own temporary disk. If it restarts,
  the documents must be saved again. The AWS setup is a demo.

## Scaling to 1000+ PDFs an hour

1000 PDFs an hour is about one every 4 seconds. One 4-page scan takes about
26 seconds of CPU time to find names and save for questions. So the load is
about 7 CPUs busy all the time. That is not much. The hard parts are
growing and shrinking with the load, keeping the stored data safe, and
long files.

1. **Add workers when the queue grows.** Start more worker copies when many
   jobs are waiting, and stop them when it is quiet. Use cheaper "spot"
   machines; a stopped job is already picked up again.
2. **Upload big batches straight to S3.** Give the caller a signed upload
   link, and start the job when the file lands. This skips the API size
   limit.
3. **Read each file with OCR only once.** Today finding names and saving
   for questions both run OCR. Keeping the OCR result by file content cuts
   the CPU work about in half.
4. **Split long files by page.** Read pages in parallel so a 100-page file
   does not block one worker for minutes.
5. **Make Qdrant stronger.** Run it with a lasting disk, copies and
   backups (or use Qdrant Cloud), and store the embeddings in a smaller
   form.
6. **Keep heavy work off Lambda.** Let Lambda take requests and read
   results, and let the workers do the heavy work.
7. **Say "busy, try later" when full.** Reply 429 when the queue is too
   long, so bursts wait in line instead of timing out.
8. **Watch it.** Alarms on queue length, the age of the oldest job,
   failed jobs and slow jobs; time spent in each step.

First, a load test at twice the target checks these numbers.

## Choosing the AI model by how hard the question is

Use three levels:
- **Easy** (one fact from one document): a small, cheap model, such as
  Nova Micro on Bedrock or a small OpenAI model.
- **Normal:** the default model, Nova Lite on Bedrock or `gpt-6-luna` on
  OpenAI (the defaults today).
- **Hard** (compare or combine many documents): a strong model, such as
  Claude Sonnet 4.6 on Bedrock or a stronger OpenAI model.

A simple rule or a small classifier picks the level, using signs such as
the length of the question, words like "compare" or "all", and how many
documents the found chunks come from. If a lower level fails or refuses,
the question is tried once more one level up. This is switched on only
after it matches the default model's scores on the answer test set.

## Extras

- **Viewer:** a plain JavaScript page with pdf.js. It sends the PDF to
  `/api/extract` and draws the boxes over the pages.
- **Docker:** `docker compose up` starts Qdrant, RabbitMQ, SeaweedFS,
  DynamoDB Local, the API, the worker and the viewer. The models are put
  inside the image when it is built, so nothing downloads at start.
- **AWS (CDK in Python):** the API runs on Lambda behind API Gateway. The
  worker and Qdrant run on Fargate. The viewer is served by S3 and
  CloudFront. Jobs use SQS, S3 and DynamoDB.
- **Tests:** fast tests use fake versions of the outside tools. Other tests
  run the real tools, and some run against real services in Docker. A score
  check on search results runs with every test run and fails if search gets
  worse. A separate check grades the AI's answers.
- **Logs and privacy:** logs are JSON lines with a request id or job id.
  Names, OCR text and file names never go into logs or error replies.
- **CI/CD:** GitHub runs all checks and tests on every push. Deploying to
  AWS is a manual button, with an option to tear everything down after.
