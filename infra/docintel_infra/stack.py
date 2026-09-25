"""The whole deployment as one stack, so one destroy removes all of it."""

import pathlib

import aws_cdk
from aws_cdk import aws_ecr_assets
from aws_cdk import aws_ecs
from aws_cdk import aws_lambda
from aws_cdk import aws_s3_deployment
import constructs

from docintel_infra import api
from docintel_infra import config
from docintel_infra import data
from docintel_infra import network
from docintel_infra import services
from docintel_infra import viewer

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
APP_DOCKERFILE = "containers/app.Dockerfile"
FRONTEND_DOCKERFILE = "containers/frontend.Dockerfile"


def service_environment(
    settings: config.InfraSettings,
    stores: data.Data,
    qdrant_url: str,
) -> dict[str, str]:
    """Builds the service's settings for the API and the worker.

    Credentials come from the roles, so no key is set.

    Args:
        settings: Deployment settings.
        stores: The tables, bucket and queues.
        qdrant_url: Private URL of Qdrant.

    Returns:
        ``DOCINTEL_*`` environment variables.
    """
    region = aws_cdk.Aws.REGION
    return {
        "DOCINTEL_CLOUD_ENV": "aws",
        "DOCINTEL_UPLOAD__MAX_BYTES": str(settings.api.upload_max_bytes),
        "DOCINTEL_QDRANT__URL": qdrant_url,
        "DOCINTEL_LLM__AWS_REGION": region,
        "DOCINTEL_LLM__DEADLINE_S": str(settings.api.llm_deadline_s),
        "DOCINTEL_BLOB__BUCKET": stores.blobs.bucket_name,
        "DOCINTEL_BLOB__REGION": region,
        "DOCINTEL_DYNAMODB__REGION": region,
        "DOCINTEL_OCCURRENCES__TABLE": stores.occurrences.table_name,
        "DOCINTEL_JOBS__DYNAMODB_TABLE": stores.jobs.table_name,
        "DOCINTEL_JOBS__MAX_ATTEMPTS": str(settings.jobs.max_attempts),
        "DOCINTEL_JOBS__LEASE_S": str(settings.jobs.lease_s),
        "DOCINTEL_QUEUE__SQS_QUEUE_URL": stores.queue.queue_url,
        "DOCINTEL_QUEUE__SQS_DEAD_LETTER_URL": stores.dead_letters.queue_url,
        "DOCINTEL_QUEUE__SQS_REGION": region,
    }


def viewer_site() -> aws_s3_deployment.ISource:
    """Returns the viewer files, built by the frontend image's site stage.

    Returns:
        The static site with pdf.js.
    """
    return aws_s3_deployment.Source.asset(
        str(REPOSITORY / "frontend"),
        bundling=aws_cdk.BundlingOptions(
            image=aws_cdk.DockerImage.from_build(
                str(REPOSITORY),
                file=FRONTEND_DOCKERFILE,
                target_stage="site",
            ),
            command=["sh", "-c", "cp -r /site/. /asset-output/"],
        ),
    )


class DocintelStack(aws_cdk.Stack):
    """API, worker, Qdrant, stores and viewer of the service."""

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        settings: config.InfraSettings,
        **kwargs: object,
    ) -> None:
        """Creates the stack.

        Args:
            scope: The CDK app.
            construct_id: Stack id.
            settings: Deployment settings.
            **kwargs: Stack properties such as ``env``.
        """
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        net = network.Network(self, "Network", settings.qdrant.namespace)
        stores = data.Data(self, "Data", settings.jobs)
        qdrant = services.Qdrant(
            self,
            "Qdrant",
            net.cluster,
            net.namespace,
            settings.qdrant,
        )
        environment = service_environment(settings, stores, qdrant.url)

        worker = services.Worker(
            self,
            "Worker",
            net.cluster,
            aws_ecs.ContainerImage.from_asset(
                str(REPOSITORY),
                file=APP_DOCKERFILE,
                target="runtime",
                platform=aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            environment,
            settings.worker,
        )
        service = api.Api(
            self,
            "Api",
            net.vpc,
            aws_lambda.DockerImageCode.from_image_asset(
                str(REPOSITORY),
                file=APP_DOCKERFILE,
                target="lambda",
                platform=aws_ecr_assets.Platform.LINUX_AMD64,
            ),
            environment,
            settings.api,
        )
        service.allow_bedrock(settings.llm)
        qdrant.allow_from(service.security_group)
        qdrant.allow_from(worker.security_group)

        for grantee in (service.function, worker.task_role):
            stores.occurrences.grant_read_write_data(grantee)
            stores.jobs.grant_read_write_data(grantee)
            stores.blobs.grant_read_write(grantee)
            stores.queue.grant_send_messages(grantee)
        stores.queue.grant_consume_messages(worker.task_role)
        stores.dead_letters.grant_send_messages(worker.task_role)

        site = viewer.Viewer(
            self,
            "Viewer",
            viewer_site(),
            service.http_api,
            origin_timeout_s=settings.viewer_origin_timeout_s,
        )
        aws_cdk.CfnOutput(
            self,
            "ViewerUrl",
            value=f"https://{site.distribution.distribution_domain_name}",
        )
        aws_cdk.CfnOutput(self, "ApiUrl", value=service.http_api.api_endpoint)
