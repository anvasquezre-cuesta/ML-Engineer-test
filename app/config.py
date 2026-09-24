"""Service configuration, read once from ``DOCINTEL_*`` variables and ``.env``.

Nested groups are addressed with ``__``, e.g. ``DOCINTEL_CHUNKING__CHUNK_SIZE``.
Settings are built in the composition root and passed to adapters; nothing
else reads the environment.
"""

import enum
import pathlib
from typing import Literal
from typing import Self

import pydantic
import pydantic_settings


class CloudEnv(enum.StrEnum):
    """Where the service runs; selects queue, blob and job-store adapters."""

    LOCAL = "local"
    AWS = "aws"


class UploadSettings(pydantic.BaseModel):
    """Limits on uploaded PDFs.

    Attributes:
        max_bytes: Largest accepted upload.
    """

    max_bytes: int = pydantic.Field(default=20 * 1024 * 1024, ge=1)


class RenderSettings(pydantic.BaseModel):
    """PDF page rendering.

    Attributes:
        dpi: Resolution pages are rendered at before OCR.
    """

    dpi: int = pydantic.Field(default=300, ge=72, le=600)


class OcrSettings(pydantic.BaseModel):
    """Tesseract OCR.

    Attributes:
        languages: Tesseract language codes joined with ``+``.
        timeout_s: Seconds before the Tesseract process is killed.
    """

    languages: str = "eng"
    timeout_s: float = pydantic.Field(default=60.0, gt=0)


class NerSettings(pydantic.BaseModel):
    """spaCy named-entity recognition.

    Attributes:
        model: Name of the installed spaCy pipeline; ``en_core_web_lg`` and the
            lighter ``en_core_web_sm`` are locked dependencies.
    """

    model: str = "en_core_web_lg"


class MatcherSettings(pydantic.BaseModel):
    """Fuzzy name matching.

    Attributes:
        threshold: Minimum similarity, in 0..1, to report a match.
    """

    threshold: float = pydantic.Field(default=0.9, ge=0.0, le=1.0)


class ChunkingSettings(pydantic.BaseModel):
    """Splitting page text into chunks at paragraph, line and sentence breaks.

    Attributes:
        chunk_size: Maximum chunk length in characters; a single word longer
            than this becomes its own oversized chunk rather than being cut.
        chunk_overlap: Characters shared by consecutive chunks.
    """

    chunk_size: int = pydantic.Field(default=800, ge=1)
    chunk_overlap: int = pydantic.Field(default=120, ge=0)

    @pydantic.model_validator(mode="after")
    def _overlap_fits_in_chunk(self) -> Self:
        """Rejects an overlap that is not smaller than the chunk size.

        Returns:
            The validated settings.

        Raises:
            ValueError: If ``chunk_overlap >= chunk_size``.
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size.")
        return self


class EmbeddingSettings(pydantic.BaseModel):
    """FastEmbed text embeddings.

    Attributes:
        model_name: FastEmbed model to load.
        cache_dir: Directory holding the model files baked into the image.
        local_files_only: Refuse to download the model; the container sets
            it so a missing model fails at startup instead of downloading.
        query_prefix: Instruction prepended to questions, never to passages.
        sparse_model_name: FastEmbed sparse model for keyword search; its
            term weights get their IDF from the vector store.
    """

    model_name: str = "BAAI/bge-small-en-v1.5"
    cache_dir: pathlib.Path = pathlib.Path(".cache/fastembed")
    local_files_only: bool = False
    query_prefix: str = (
        "Represent this sentence for searching relevant passages: "
    )
    sparse_model_name: str = "Qdrant/bm25"


class QdrantSettings(pydantic.BaseModel):
    """Qdrant vector store.

    Attributes:
        url: Qdrant HTTP endpoint.
        api_key: API key, if the server requires one.
        collection_prefix: Collection name prefix; the model slug is appended.
        timeout_s: Per-attempt timeout in whole seconds, as the client takes.
        max_retries: Retries after the first attempt on transient failures.
        backoff_initial_s: First wait before a retry; waits grow
            exponentially with jitter.
        backoff_max_s: Longest wait between two attempts.
        deadline_s: Total time one operation may take, retries included.
        top_k: Chunks retrieved per question.
        prefetch_limit: Candidates each of the dense and keyword searches
            passes to rank fusion.
        rrf_k: Reciprocal-rank-fusion constant; Qdrant's default is 2.
        corpus_idf: Compute keyword IDF over the points stored now; without
            it Qdrant also counts deleted points.
    """

    url: str = "http://localhost:6333"
    api_key: pydantic.SecretStr | None = None
    collection_prefix: str = "chunks"
    timeout_s: int = pydantic.Field(default=5, ge=1)
    max_retries: int = pydantic.Field(default=2, ge=0)
    backoff_initial_s: float = pydantic.Field(default=0.2, ge=0)
    backoff_max_s: float = pydantic.Field(default=2.0, ge=0)
    deadline_s: float = pydantic.Field(default=15.0, gt=0)
    top_k: int = pydantic.Field(default=8, ge=1)
    prefetch_limit: int = pydantic.Field(default=100, ge=1)
    rrf_k: int = pydantic.Field(default=60, ge=1)
    corpus_idf: bool = True


class LlmSettings(pydantic.BaseModel):
    """Chat model used to answer questions.

    Attributes:
        provider: ``bedrock`` or ``openai``.
        bedrock_model: Bedrock model or inference profile id.
        openai_model: Model id on the OpenAI-compatible endpoint.
        openai_base_url: Endpoint of any OpenAI-compatible API; empty uses
            OpenAI.
        openai_api_key: Key for the OpenAI-compatible endpoint.
        aws_region: AWS region for Bedrock.
        aws_profile: Named AWS profile for Bedrock; empty uses the keys below
            or the task role.
        aws_access_key_id: Access key for Bedrock; empty uses the profile or
            the task role.
        aws_secret_access_key: Secret key paired with ``aws_access_key_id``.
        timeout_s: Per-attempt timeout.
        max_retries: Retries after the first attempt, done by the provider
            SDK, which honours the provider's Retry-After.
        deadline_s: Total time one call may take, SDK retries included.
        temperature: Bedrock sampling temperature; 0 keeps answers
            reproducible.
        openai_temperature: OpenAI sampling temperature; empty leaves the
            model's default, the only value reasoning models accept.
        max_tokens: Longest completion.
        reasoning_effort: Reasoning effort for OpenAI reasoning models;
            empty leaves the model's default.
    """

    provider: Literal["bedrock", "openai"] = "bedrock"
    bedrock_model: str = "us.amazon.nova-lite-v1:0"
    openai_model: str = "gpt-6-luna"
    openai_base_url: str = ""
    openai_api_key: pydantic.SecretStr | None = None
    aws_region: str = "us-east-1"
    aws_profile: str = ""
    aws_access_key_id: pydantic.SecretStr | None = None
    aws_secret_access_key: pydantic.SecretStr | None = None
    timeout_s: float = pydantic.Field(default=30.0, gt=0)
    max_retries: int = pydantic.Field(default=2, ge=0)
    deadline_s: float = pydantic.Field(default=60.0, gt=0)
    temperature: float = pydantic.Field(default=0.0, ge=0)
    openai_temperature: float | None = pydantic.Field(default=None, ge=0)
    max_tokens: int = pydantic.Field(default=2048, ge=1)
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None


class LlmObservabilitySettings(pydantic.BaseModel):
    """Langfuse tracing of LLM calls; disabled while keys are empty.

    Attributes:
        langfuse_host: Langfuse server URL.
        langfuse_public_key: Project public key.
        langfuse_secret_key: Project secret key.
    """

    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: pydantic.SecretStr | None = None
    langfuse_secret_key: pydantic.SecretStr | None = None


class BlobSettings(pydantic.BaseModel):
    """S3-compatible storage for staged uploads and job results.

    Attributes:
        bucket: Bucket name.
        endpoint_url: Custom S3-compatible endpoint; empty uses AWS S3.
        access_key_id: Access key; empty uses the task role.
        secret_access_key: Secret key; empty uses the task role.
        region: Bucket region.
        timeout_s: Connect and read timeout of each request.
        max_retries: Retries after the first attempt, done by botocore.
    """

    bucket: str = "docintel"
    endpoint_url: str = ""
    access_key_id: pydantic.SecretStr | None = None
    secret_access_key: pydantic.SecretStr | None = None
    region: str = "us-east-1"
    timeout_s: float = pydantic.Field(default=10.0, gt=0)
    max_retries: int = pydantic.Field(default=3, ge=0)


class QueueSettings(pydantic.BaseModel):
    """Job queue: RabbitMQ locally, SQS on AWS.

    Attributes:
        rabbitmq_url: AMQP URL, including credentials.
        sqs_queue_url: URL of the SQS work queue.
        sqs_dead_letter_url: URL of the SQS dead-letter queue.
        retry_delay_s: Backoff before a transient failure is retried.
    """

    rabbitmq_url: pydantic.SecretStr = pydantic.SecretStr(
        "amqp://guest:guest@localhost:5672/"
    )
    sqs_queue_url: str = ""
    sqs_dead_letter_url: str = ""
    retry_delay_s: float = pydantic.Field(default=30.0, ge=0)


class DynamoDbSettings(pydantic.BaseModel):
    """DynamoDB access shared by the occurrence and job stores.

    Attributes:
        endpoint_url: Custom endpoint (DynamoDB Local); empty uses AWS.
        region: AWS region.
        access_key_id: Access key; empty uses the task role.
        secret_access_key: Secret key paired with ``access_key_id``.
        timeout_s: Connect and read timeout of each request.
        max_retries: Retries after the first attempt, done by botocore.
        create_tables: Create missing tables at startup (DynamoDB Local);
            on AWS the tables come from the infrastructure code.
    """

    endpoint_url: str = ""
    region: str = "us-east-1"
    access_key_id: pydantic.SecretStr | None = None
    secret_access_key: pydantic.SecretStr | None = None
    timeout_s: float = pydantic.Field(default=5.0, gt=0)
    max_retries: int = pydantic.Field(default=3, ge=0)
    create_tables: bool = False


class OccurrenceSettings(pydantic.BaseModel):
    """Store of every extracted name occurrence.

    Attributes:
        table: DynamoDB table name.
        batch_max_attempts: Batch writes tried before unprocessed items
            fail the generation.
        batch_backoff_s: First backoff before resending unprocessed items;
            it doubles with each attempt.
    """

    table: str = "docintel-occurrences"
    batch_max_attempts: int = pydantic.Field(default=5, ge=1)
    batch_backoff_s: float = pydantic.Field(default=0.05, ge=0)


class JobSettings(pydantic.BaseModel):
    """Asynchronous job tracking in DynamoDB.

    Attributes:
        max_attempts: Attempts before a job is dead-lettered.
        lease_s: Seconds a worker owns a running job.
        queued_stale_s: Seconds a job may wait in ``queued`` before the
            reaper publishes it again.
        reap_limit: Most jobs of each kind handled per reaper pass.
        dynamodb_table: DynamoDB table name.
    """

    max_attempts: int = pydantic.Field(default=3, ge=1)
    lease_s: float = pydantic.Field(default=300.0, gt=0)
    queued_stale_s: float = pydantic.Field(default=120.0, gt=0)
    reap_limit: int = pydantic.Field(default=100, ge=1)
    dynamodb_table: str = "docintel-jobs"


class CpuSettings(pydantic.BaseModel):
    """CPU-bound work (rendering, OCR, NER, embeddings).

    Attributes:
        max_concurrency: Calls allowed to run at the same time per process.
    """

    max_concurrency: int = pydantic.Field(default=2, ge=1)


class PromptSettings(pydantic.BaseModel):
    """Prompt template files.

    Attributes:
        directory: Folder holding the prompt templates; defaults to the
            templates shipped with the app.
    """

    directory: pathlib.Path = pathlib.Path(__file__).parent / "prompts"


class EvalSettings(pydantic.BaseModel):
    """Offline answer evaluation (``invoke eval``).

    Attributes:
        judge_model: Bedrock model that grades answers; must not share a
            family with the generator.
        runs: Repeats of the whole question set, to expose run-to-run noise.
        concurrency: Questions evaluated at the same time.
        max_judge_calls: Judge calls allowed per evaluation; the run stops
            when it is spent.
        report_dir: Where the reports and per-question outcomes are written.
        question_sets: ``samples`` (the verified questions and their
            evidence-withheld copies) and ``reworded`` (reworded and
            near-miss questions).
        split: Split of the reworded set to run.
        requests_per_minute: Generator calls allowed per minute; empty
            leaves them unpaced.
    """

    judge_model: str = "us.anthropic.claude-sonnet-4-6"
    runs: int = pydantic.Field(default=3, ge=1)
    concurrency: int = pydantic.Field(default=4, ge=1)
    max_judge_calls: int = pydantic.Field(default=1500, ge=1)
    report_dir: pathlib.Path = pathlib.Path(".cache/eval/reports")
    question_sets: list[Literal["samples", "reworded"]] = [
        "samples",
        "reworded",
    ]
    split: Literal["all", "dev", "heldout"] = "all"
    requests_per_minute: int | None = pydantic.Field(default=None, ge=1)


class LoggingSettings(pydantic.BaseModel):
    """Structured logging.

    Attributes:
        level: Minimum level, e.g. ``INFO``.
        json_output: Render JSON lines; ``False`` renders console output.
    """

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_output: bool = True


class Settings(pydantic_settings.BaseSettings):
    """Every setting of the service, grouped by concern.

    Attributes:
        cloud_env: Where the service runs.
        upload: Upload limits.
        render: Page rendering.
        ocr: Tesseract OCR.
        ner: spaCy NER.
        matcher: Fuzzy name matching.
        chunking: Text chunking.
        embeddings: FastEmbed embeddings.
        qdrant: Qdrant vector store.
        llm: Chat model.
        prompts: Prompt template files.
        llm_observability: Langfuse tracing.
        blob: Object storage.
        queue: Job queue.
        dynamodb: DynamoDB access.
        occurrences: Name occurrence store.
        jobs: Job tracking.
        cpu: CPU-bound work.
        logging: Structured logging.
        eval: Offline answer evaluation.
    """

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="DOCINTEL_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    cloud_env: CloudEnv = CloudEnv.LOCAL
    upload: UploadSettings = UploadSettings()
    render: RenderSettings = RenderSettings()
    ocr: OcrSettings = OcrSettings()
    ner: NerSettings = NerSettings()
    matcher: MatcherSettings = MatcherSettings()
    chunking: ChunkingSettings = ChunkingSettings()
    embeddings: EmbeddingSettings = EmbeddingSettings()
    qdrant: QdrantSettings = QdrantSettings()
    llm: LlmSettings = LlmSettings()
    prompts: PromptSettings = PromptSettings()
    llm_observability: LlmObservabilitySettings = LlmObservabilitySettings()
    blob: BlobSettings = BlobSettings()
    queue: QueueSettings = QueueSettings()
    dynamodb: DynamoDbSettings = DynamoDbSettings()
    occurrences: OccurrenceSettings = OccurrenceSettings()
    jobs: JobSettings = JobSettings()
    cpu: CpuSettings = CpuSettings()
    logging: LoggingSettings = LoggingSettings()
    eval: EvalSettings = EvalSettings()
