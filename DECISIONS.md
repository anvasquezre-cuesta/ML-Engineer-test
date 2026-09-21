# Engineering Decisions

## LLM Provider and Configuration

The application was developed and tested locally with Ollama and Llama 3 because the development environment does not rely on paid external LLM API credits.

The assignment specifies an OpenAI-compatible LLM endpoint with a configurable base URL and API key. To satisfy that requirement without coupling the RAG application to a specific vendor, the LLM interaction is defined through the `LLMProvider` abstraction.

LLM configuration is centralized in `app/config.py`. The module defines environment-overridable settings for the provider, model, base URL, API key, temperature, timeout, and retry policy. The default configuration supports the local Ollama setup.

The application currently provides:

* Ollama for local development and validation.
* An OpenAI-compatible HTTP provider for evaluation and deployment endpoints.

The RAG service depends only on the `LLMProvider` interface. Provider selection, model name, endpoint, credentials, timeout, temperature, and retry behavior are supplied through the configuration defined in `app/config.py`.

The evaluator does not need to modify `app/config.py`. Instead, the relevant `APP_*` environment variables can be overridden in the evaluation environment, such as `APP_LLM_PROVIDER`, `APP_LLM_MODEL`, `APP_LLM_BASE_URL`, and `APP_LLM_API_KEY`. This keeps deployment-specific configuration and credentials outside the application source code.

This allows the same RAG implementation to be tested locally with Ollama and configured for an evaluator-provided OpenAI-compatible endpoint without changing the application logic.

The implementation does not claim native support for proprietary provider-specific APIs that do not expose an OpenAI-compatible interface. Supporting such an API would require an additional provider adapter.


## Notable Engineering Decisions and Trade-offs

* **Separated text chunking from the RAG service**

  * The original skeleton placed text chunking directly inside the RAG service.
  * I moved this responsibility into a dedicated `TextChunker` component so that RAG orchestration is not responsible for both document preprocessing and retrieval/generation.
  * This follows separation of concerns and makes chunking independently testable and configurable.
  * Trade-off: it introduces another small component, but keeps the RAG service focused on retrieval and answer generation.

* **Thin FastAPI routers, business logic in services**

  * HTTP concerns stay in the API layer while OCR, extraction, ingestion, and RAG orchestration remain independently testable.
  * Trade-off: more classes and modules than a small script, but clearer responsibilities and easier testing.

* **Constructor-based dependency injection**

  * Services receive their dependencies explicitly instead of creating them internally.
  * This makes external components easier to replace with test doubles and keeps business logic independent from HTTP.

* **`LLMProvider` Protocol**

  * RAG depends on an application-level LLM abstraction rather than directly on Ollama.
  * This allows the LLM implementation to be replaced without changing the RAG service.
  * Trade-off: the current implementation supports only the Ollama provider required for development; additional providers can be added later.

* **Vector-store adapter boundary**

  * ChromaDB is hidden behind the application-owned `VectorStoreService` rather than being accessed directly by the RAG or ingestion orchestration.
  * The RAG service works with our own vector-store operations and result model instead of depending on ChromaDB-specific APIs.
  * This means another vector-store implementation could replace ChromaDB without changing the RAG business logic.
  * ChromaDB was selected because the assignment explicitly allows an embedded/in-process vector store and it keeps the take-home implementation simple.
  * Trade-off: the current ChromaDB deployment is local and embedded, so a higher-scale production architecture would likely use a distributed or managed vector database. The application boundary makes that infrastructure change more localized.

* **Local OCR with PyMuPDF and Tesseract**

  * PDF pages are rendered and OCR is performed on every page, preserving word-level coordinates.
  * This provides the information required to return bounding boxes in PDF coordinates.
  * Trade-off: OCR quality depends on document quality and the Tesseract model.

* **Simple full-string fuzzy matching**

  * Names are normalized for case, accents, whitespace, and punctuation before similarity is calculated.
  * A configurable threshold avoids accepting weak matches.
  * Trade-off: this is intentionally simpler than a full entity-resolution system and is appropriate for the assignment's matching requirement.

* **Word-safe recursive chunking**

  * Chunks are created with recursive separators that include whitespace boundaries.
  * This avoids cutting words arbitrarily while keeping the implementation simple.
  * Trade-off: this does not implement more advanced semantic or document-structure-aware chunking.

* **Evaluation-driven retrieval configuration**

  * RAG retrieval was evaluated with representative questions rather than choosing retrieval parameters arbitrarily.
  * An initial `top_k=5` configuration missed relevant evidence for one question. Increasing it to 12 exposed the relevant chunk without requiring a more complex retrieval pipeline.
  * Trade-off: retrieving more context can increase prompt size and potentially introduce less relevant information.
  * This demonstrates a preference for measuring the simple architecture first before adding hybrid search, reranking, query rewriting, or other retrieval complexity.

* **Testing and RAG evaluation are separate concerns**

  * Engineering tests validate software behavior through unit, integration, and E2E tests.
  * RAG evaluation separately examines retrieval relevance, answer correctness, groundedness, unavailable-answer behavior, and source correctness.
  * This distinction is important because passing software tests does not demonstrate that a RAG system retrieves the right evidence or produces good answers.
  * Trade-off: a lightweight representative evaluation was chosen instead of introducing a large evaluation framework, benchmark, or complex LLM-as-judge system.

* **Safety and guardrails are part of the RAG architecture**

  * The RAG flow is explicitly designed to answer only from retrieved context.
  * When evidence is insufficient, the service returns an unavailable-answer response rather than intentionally generating an answer from outside knowledge.
  * Retrieved document content is treated as data rather than instructions, providing a basic defense against prompt injection contained in documents.
  * Sources are controlled by application retrieval metadata rather than being invented by the LLM.
  * Trade-off: these are deliberately lightweight guardrails appropriate for the assignment; a production system would require broader security, access-control, content-safety, and adversarial testing.

* **Observability and monitoring are included proportionally**

  * RAG and ingestion operations emit contextual logs containing operational information such as document IDs, status, duration, retrieved chunk IDs, provider/model, and failure type.
  * Full document contents, prompts, questions, and generated answers are intentionally excluded from logs.
  * Trade-off: the take-home uses standard Python logging rather than introducing a full observability stack. A production deployment could add centralized structured logs, metrics, tracing, dashboards, and alerts.

* **Grounded RAG with application-controlled sources**

  * The LLM receives only retrieved document context and is instructed not to use outside knowledge.
  * Sources are taken from retrieval metadata rather than generated by the LLM.
  * If no context is retrieved, the service returns an unavailable-answer response instead of calling the model.
  * Trade-off: the simple approach does not guarantee factual correctness when the retrieved context itself is ambiguous or incorrect.

* **Retries and timeouts at the LLM boundary**

  * The Ollama provider uses a configurable timeout and retry count.
  * Provider-specific failures are translated into an application-level error.
  * Trade-off: retries increase latency when the dependency remains unavailable, so the number of attempts is deliberately limited.

* **No network retries for ChromaDB**

  * ChromaDB runs as an embedded local component in this implementation, so network-style retry logic is unnecessary.
  * Vector-store failures are still translated into a controlled application error.
  * If the vector store becomes a remote service, retry and connection policies should be reconsidered.

* **Temporary-file validation and cleanup**

  * Uploaded files are size-limited, checked as readable PDFs, and removed after processing.
  * Cleanup is handled explicitly even when processing fails.
  * A byte-stream PDF validation approach was used to avoid Windows file-locking issues encountered when validating a temporary file while PyMuPDF still had it open.

## AI Tooling Disclosure

* ChatGPT was used extensively as an engineering assistant throughout the take-home.
* The process began with analyzing the assignment requirements and translating them into a staged development plan covering OCR/NER, bounding boxes, fuzzy name matching, RAG, production engineering, final assignment review, documentation, and final repository checks.
* During each stage, ChatGPT was used for code drafting, implementation reasoning, debugging assistance, test design, architectural discussion, documentation drafting, and reviewing alternatives. Development decisions were made iteratively as implementation issues and test results were encountered.
* The implementation was reviewed and validated locally through the project's test suite, real sample documents, OCR processing, ChromaDB retrieval, and the local Ollama/Llama 3 workflow.
* The final design and implementation were reviewed against the assignment requirements, including architecture, correctness, testing and evaluation, safety and guardrails, observability, resilience, resource management, and documentation.
* The submitted implementation was examined to ensure that its behavior, design decisions, trade-offs, limitations, and failure modes could be explained and defended.
* AI assistance was treated as an engineering tool rather than as a substitute for implementation validation, testing, or understanding of the resulting system.

