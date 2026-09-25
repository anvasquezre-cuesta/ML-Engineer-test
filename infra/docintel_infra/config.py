"""Deployment settings, read from ``DOCINTEL_INFRA__*`` variables or ``.env``.

The deploy credentials fall back to the AWS keys the service's own settings
already hold, so one ``.env`` serves both.
"""

import pydantic
import pydantic_settings


class ApiSettings(pydantic.BaseModel):
    """The API Lambda.

    Attributes:
        memory_mb: Lambda memory; CPU grows with it (1,769 MB is one vCPU).
        timeout_s: Lambda timeout; long enough for a cold environment to
            finish loading the models (about a minute) instead of being
            recycled before it is ready.
        provisioned_concurrency: Environments kept initialized, so requests
            never wait for a cold start.
        upload_max_bytes: Upload cap, below Lambda's 6 MB request payload.
        llm_deadline_s: LLM budget per request, under the gateway's 30 s.
    """

    memory_mb: int = pydantic.Field(default=4096, ge=128, le=10240)
    timeout_s: int = pydantic.Field(default=180, ge=1, le=900)
    provisioned_concurrency: int = pydantic.Field(default=4, ge=1)
    upload_max_bytes: int = pydantic.Field(default=4_194_304, ge=1)
    llm_deadline_s: float = pydantic.Field(default=20.0, gt=0, lt=30)


class WorkerSettings(pydantic.BaseModel):
    """The job worker's Fargate task.

    Attributes:
        cpu: Task CPU units (1024 is one vCPU).
        memory_mb: Task memory; holds the spaCy and FastEmbed models.
    """

    cpu: int = 1024
    memory_mb: int = 3072


class QdrantSettings(pydantic.BaseModel):
    """The Qdrant Fargate task.

    Attributes:
        image: Pinned Qdrant image.
        cpu: Task CPU units.
        memory_mb: Task memory.
        namespace: Private DNS namespace the task registers in.
        service_name: DNS name of the task inside the namespace.
    """

    image: str = "qdrant/qdrant:v1.19.1"
    cpu: int = 512
    memory_mb: int = 1024
    namespace: str = "docintel.local"
    service_name: str = "qdrant"


class JobSettings(pydantic.BaseModel):
    """Job queue sizing; must agree with the service's job settings.

    Attributes:
        max_attempts: Attempts before the worker dead-letters a job.
        lease_s: Seconds a worker owns a running job.
        visibility_timeout_s: SQS visibility; outlasts the lease.
        dead_letter_retention_days: How long dead letters are kept.
    """

    max_attempts: int = pydantic.Field(default=3, ge=1)
    lease_s: int = pydantic.Field(default=300, ge=1)
    visibility_timeout_s: int = pydantic.Field(default=360, ge=1)
    dead_letter_retention_days: int = pydantic.Field(default=14, ge=1, le=14)

    @pydantic.model_validator(mode="after")
    def _visibility_outlasts_lease(self) -> "JobSettings":
        """Rejects a visibility timeout that a running job can outlive.

        Returns:
            The settings.

        Raises:
            ValueError: If the visibility timeout is not above the lease.
        """
        if self.visibility_timeout_s <= self.lease_s:
            raise ValueError("visibility_timeout_s must exceed lease_s.")
        return self


class LlmSettings(pydantic.BaseModel):
    """The Bedrock model the API may invoke.

    Attributes:
        inference_profile: Cross-region inference profile id.
        foundation_model: Model id behind the profile.
        model_regions: Regions the profile routes requests to.
    """

    inference_profile: str = "us.amazon.nova-lite-v1:0"
    foundation_model: str = "amazon.nova-lite-v1:0"
    model_regions: tuple[str, ...] = ("us-east-1", "us-east-2", "us-west-2")


class InfraSettings(pydantic_settings.BaseSettings):
    """Everything the CDK app and its deploy tasks need.

    Attributes:
        stack_name: CloudFormation stack name.
        region: Region to deploy to.
        cdk_cli_version: Pinned AWS CDK CLI run through npx.
        viewer_origin_timeout_s: How long CloudFront waits for the API.
        aws_access_key_id: Deploy access key; falls back to the LLM key.
        aws_secret_access_key: Deploy secret; falls back to the LLM secret.
        api: The API Lambda.
        worker: The worker task.
        qdrant: The Qdrant task.
        jobs: Job queue sizing.
        llm: The Bedrock model.
    """

    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="DOCINTEL_INFRA__",
        env_nested_delimiter="__",
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    stack_name: str = "Docintel"
    region: str = "us-east-1"
    cdk_cli_version: str = "2.1143.0"
    viewer_origin_timeout_s: int = pydantic.Field(default=60, ge=1, le=120)
    aws_access_key_id: pydantic.SecretStr | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices(
            "DOCINTEL_INFRA__AWS_ACCESS_KEY_ID",
            "DOCINTEL_LLM__AWS_ACCESS_KEY_ID",
        ),
    )
    aws_secret_access_key: pydantic.SecretStr | None = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices(
            "DOCINTEL_INFRA__AWS_SECRET_ACCESS_KEY",
            "DOCINTEL_LLM__AWS_SECRET_ACCESS_KEY",
        ),
    )
    api: ApiSettings = ApiSettings()
    worker: WorkerSettings = WorkerSettings()
    qdrant: QdrantSettings = QdrantSettings()
    jobs: JobSettings = JobSettings()
    llm: LlmSettings = LlmSettings()
