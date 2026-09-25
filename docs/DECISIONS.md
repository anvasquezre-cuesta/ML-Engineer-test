# Decisions

The main choices, why they were made, and what they cost.

## 1. Ports and adapters
- **Choice:** the rules of the service sit in the middle. Every outside tool
  (OCR, AI, database, queue, and so on) sits behind a small fixed interface.
  One file connects the real tools. The web routes stay thin.
- **Why:** a tool can be swapped (for example OpenAI for Bedrock, RabbitMQ
  for SQS) without touching the rules. Tests can use fake tools and run fast.
- **Cost:** more files and more small classes than a simple script.

## 2. Quick replies plus background jobs
- **Choice:** the three endpoints in the task answer right away. Extra job
  endpoints put the work in a queue (a waiting line). A worker does it, and
  the caller checks the job state later.
- **Why:** big files or many files should not keep a web request open. A
  job that fails can be retried, and one that keeps failing is set aside for
  a person to check.
- **Cost:** more moving parts: a queue, a worker, file storage and job
  records.

## 3. OCR every page at 300 dpi, boxes from the OCR words
- **Choice:** every page, the first one too, is turned into a picture at
  300 dpi and read with Tesseract. Each name's box is built from the
  positions of its words, one box per name, in PDF points from the top-left
  corner of the page. Titles like "Dr." are left out of the box.
- **Why:** the box is tied to the exact words of the name, so two names on
  one line never share a box.
- **Cost:** 300 dpi is slower than a lower setting. The expected corner (top
  or bottom) was not stated in the task, so top-left was picked because it
  matches PyMuPDF and common OCR services.

## 4. spaCy large English model
- **Choice:** `en_core_web_lg` finds the names. It is locked in the
  dependency file, so it is installed with everything else and never
  downloaded at start.
- **Why:** in the tests it was the only model without heavy AI libraries
  that found the sample names with no wrong boxes, and it is as fast as the
  small model.
- **Cost:** a bigger image. It is still not perfect: it misses "Björn" in
  one sample.

## 5. How names are matched
- **Choice:** rapidfuzz compares the whole name, in any word order, after
  removing case and accents. Common OCR mistakes inside names (1 for l, 0
  for o) are fixed first. The default pass mark is 0.9, and it can be
  changed.
- **Why:** it finds real names damaged by OCR ("Nufez" for "Núñez") and
  reversed names ("Williams, Sarah"), but not part of a name ("Lucas" does
  not match "Lucas Moreau").
- **Cost:** names one letter apart can pass (Park and Parker score 0.93).
  The score is shown so a person can decide.

## 6. Small embedding model and sentence-based pieces
- **Choice:** FastEmbed with `bge-small-en-v1.5` turns text into numbers.
  Text is split into pieces of about 800 letters, at paragraph, line or
  sentence ends, never inside a word.
- **Why:** bigger models were not clearly better on these documents but are
  slower and larger. Splitting by meaning was tested and gave no clear gain.
- **Cost:** English only.

## 7. Search by meaning and by keywords, no re-ranker
- **Choice:** Qdrant searches the pieces two ways (by meaning and by
  keywords) and mixes the two result lists. There is no second AI step to
  re-sort them.
- **Why:** keyword search catches names, numbers and exact terms that the
  meaning search can miss. The mixed search already found the right piece
  for the test questions.
- **Cost:** a known Qdrant keyword-scoring issue after deletes had to be
  worked around and is covered by a test.

## 8. Answers only from the found text
- **Choice:** the AI gets only the found pieces. It must mark each fact with
  the piece number, or say the fixed sentence "I cannot answer this from the
  provided documents." Sources are taken only from the pieces it marked.
  All prompt text lives in files.
- **Why:** answers stay grounded, and the sources can always be checked.
- **Cost:** some answerable but oddly worded questions get refused.

## 9. OpenAI or Bedrock, and the default models
- **Choice:** one LangChain adapter supports OpenAI and AWS Bedrock, picked
  in settings. Locally the default is OpenAI (`gpt-6-luna`), so only an API
  key is needed. On AWS it is Bedrock Nova Lite.
- **Why:** Nova Lite passed the answer tests and was the cheapest and
  fastest option.
- **Cost:** a cheap model can fail on hard, multi-document questions.

## 10. Time limits and retries everywhere
- **Choice:** every call to Qdrant and to the AI has a time limit, a small
  number of retries with growing waits, and a total deadline. After that, a
  clear error (502, 503 or 504) is returned.
- **Why:** one slow service should not hang the whole request, and short
  hiccups should not become errors.
- **Cost:** in the worst case a request waits for all its retries before it
  fails.

## 11. DynamoDB for job records and found names
- **Choice:** DynamoDB holds the job states and the names found in each
  document. Each run of a document is saved in full first, then switched on
  in one step, so a reader never sees half a result. Changes to a job's
  state only happen if the state is still the expected one.
- **Why:** no server to run, low cost on AWS and no table changes to manage.
  Two workers can never both take the same job.
- **Cost:** harder to query freely than a normal SQL database.

## 12. AWS: Lambda API, Fargate worker and Qdrant
- **Choice:** the same app image runs the API on Lambda behind API Gateway.
  The worker and Qdrant run on Fargate. The viewer is on S3 and CloudFront.
  Everything is written in CDK with Python.
- **Why:** no load balancer, low cost when idle, and the app code does not
  change for AWS.
- **Cost:** loading the models takes about a minute, so 4 Lambda copies are
  kept warm. Uploads are limited to 4 MB on AWS. Qdrant keeps its data on
  its own temporary disk, so this setup is a demo, not a production setup.

## Known gaps
- A password-protected PDF returns a general 500 error instead of a clear
  one.
- The request logging layer could be rewritten in a lighter style.

## Use of AI tools
- Claude Code (Claude Opus) wrote most of the code, tests, Docker files and
  AWS setup, under my direction.
- I made every decision. Each choice was put to me, and I approved or
  changed it.
- I reviewed the code, ran the tests, the local stack and the AWS deploy,
  and made every commit myself.
