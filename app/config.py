"""Service configuration, read once from ``DOCINTEL_*`` variables and ``.env``.

Nested groups are addressed with ``__``, e.g. ``DOCINTEL_CHUNKING__CHUNK_SIZE``.
Settings are built in the composition root and passed to adapters; nothing
else reads the environment.
"""

import enum
from pathlib import Path
from typing import Literal
from typing import Self

from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr
from pydantic import model_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class CloudEnv(enum.StrEnum):
    """Where the service runs; selects queue, blob and job-store adapters."""

    LOCAL = "local"
    AWS = "aws"


class UploadSettings(BaseModel):
    """Limits on uploaded PDFs.

    Attributes:
        max_bytes: Largest accepted upload.
    """

    max_bytes: int = Field(default=20 * 1024 * 1024, ge=1)


class RenderSettings(BaseModel):
    """PDF page rendering.

    Attributes:
        dpi: Resolution pages are rendered at before OCR.
    """

    dpi: int = Field(default=300, ge=72, le=600)


class OcrSettings(BaseModel):
    """Tesseract OCR.

    Attributes:
        languages: Tesseract language codes joined with ``+``.
        timeout_s: Seconds before the Tesseract process is killed.
    """

    languages: str = "eng"
    timeout_s: float = Field(default=60.0, gt=0)


class NerSettings(BaseModel):
    """spaCy named-entity recognition.

    Attributes:
        model: Name of the installed spaCy pipeline.
    """

    model: str = "en_core_web_sm"


class MatcherSettings(BaseModel):
    """Fuzzy name matching.

    Attributes:
        threshold: Minimum similarity, in 0..1, to report a match.
    """

    threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class ChunkingSettings(BaseModel):
    """Splitting page text into chunks.

    Attributes:
        strategy: ``sentence`` or ``semantic``.
        chunk_size: Maximum chunk length in characters.
        chunk_overlap: Characters shared by consecutive chunks.
        semantic_breakpoint_percentile: Distance percentile at which the
            semantic strategy starts a new chunk.
    """

    strategy: Literal["sentence", "semantic"] = "sentence"
    chunk_size: int = Field(default=800, ge=1)
    chunk_overlap: int = Field(default=120, ge=0)
    semantic_breakpoint_percentile: float = Field(default=95.0, gt=0, le=100)

    @model_validator(mode="after")
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


class EmbeddingSettings(BaseModel):
    """FastEmbed text embeddings.

    Attributes:
        model_name: FastEmbed model to load.
        cache_dir: Directory holding the model files baked into the image.
        query_prefix: Instruction prepended to questions, never to passages.
    """

    model_name: str = "BAAI/bge-small-en-v1.5"
    cache_dir: Path = Path(".cache/fastembed")
    query_prefix: str = (
        "Represent this sentence for searching relevant passages: "
    )


class QdrantSettings(BaseModel):
    """Qdrant vector store.

    Attributes:
        url: Qdrant HTTP endpoint.
        api_key: API key, if the server requires one.
        collection_prefix: Collection name prefix; the model slug is appended.
        timeout_s: Per-request timeout.
        max_retries: Retries on transient failures.
        top_k: Chunks retrieved per question.
    """

    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None
    collection_prefix: str = "chunks"
    timeout_s: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    top_k: int = Field(default=5, ge=1)


class LlmSettings(BaseModel):
    """Chat model used to answer questions.

    Attributes:
        provider: ``bedrock`` or ``openai``.
        model: Model id; empty uses the provider default.
        openai_api_key: OpenAI key, required for the OpenAI provider.
        aws_region: AWS region for Bedrock.
        aws_profile: Named AWS profile for Bedrock; empty uses the task role.
        timeout_s: Per-request timeout.
        max_retries: Retries on transient failures.
    """

    provider: Literal["bedrock", "openai"] = "bedrock"
    model: str = ""
    openai_api_key: SecretStr | None = None
    aws_region: str = "us-east-1"
    aws_profile: str = ""
    timeout_s: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


class LlmObservabilitySettings(BaseModel):
    """Langfuse tracing of LLM calls; disabled while keys are empty.

    Attributes:
        langfuse_host: Langfuse server URL.
        langfuse_public_key: Project public key.
        langfuse_secret_key: Project secret key.
    """

    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None


class BlobSettings(BaseModel):
    """S3-compatible storage for staged uploads and job results.

    Attributes:
        bucket: Bucket name.
        endpoint_url: Custom endpoint (MinIO); empty uses AWS S3.
        access_key_id: Access key; empty uses the task role.
        secret_access_key: Secret key; empty uses the task role.
        region: Bucket region.
    """

    bucket: str = "docintel"
    endpoint_url: str = ""
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str = "us-east-1"


class QueueSettings(BaseModel):
    """Job queue: RabbitMQ locally, SQS on AWS.

    Attributes:
        rabbitmq_url: AMQP URL, including credentials.
        sqs_queue_url: URL of the SQS work queue.
        sqs_dead_letter_url: URL of the SQS dead-letter queue.
        retry_delay_s: Backoff before a transient failure is retried.
    """

    rabbitmq_url: SecretStr = SecretStr("amqp://guest:guest@localhost:5672/")
    sqs_queue_url: str = ""
    sqs_dead_letter_url: str = ""
    retry_delay_s: float = Field(default=30.0, ge=0)


class JobSettings(BaseModel):
    """Asynchronous job tracking.

    Attributes:
        repository: ``dynamodb`` or ``postgres``.
        max_attempts: Attempts before a job is dead-lettered.
        lease_s: Seconds a worker owns a running job.
        dynamodb_table: DynamoDB table name.
        dynamodb_endpoint_url: Custom endpoint (DynamoDB Local).
        postgres_dsn: Async SQLAlchemy URL for the Postgres repository.
    """

    repository: Literal["dynamodb", "postgres"] = "dynamodb"
    max_attempts: int = Field(default=3, ge=1)
    lease_s: float = Field(default=300.0, gt=0)
    dynamodb_table: str = "docintel-jobs"
    dynamodb_endpoint_url: str = ""
    postgres_dsn: SecretStr | None = None


class CpuSettings(BaseModel):
    """CPU-bound work (rendering, OCR, NER, embeddings).

    Attributes:
        max_concurrency: Calls allowed to run at the same time per process.
    """

    max_concurrency: int = Field(default=2, ge=1)


class LoggingSettings(BaseModel):
    """Structured logging.

    Attributes:
        level: Minimum level, e.g. ``INFO``.
        json_output: Render JSON lines; ``False`` renders console output.
    """

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_output: bool = True


class Settings(BaseSettings):
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
        llm_observability: Langfuse tracing.
        blob: Object storage.
        queue: Job queue.
        jobs: Job tracking.
        cpu: CPU-bound work.
        logging: Structured logging.
    """

    model_config = SettingsConfigDict(
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
    llm_observability: LlmObservabilitySettings = LlmObservabilitySettings()
    blob: BlobSettings = BlobSettings()
    queue: QueueSettings = QueueSettings()
    jobs: JobSettings = JobSettings()
    cpu: CpuSettings = CpuSettings()
    logging: LoggingSettings = LoggingSettings()
