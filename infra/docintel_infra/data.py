"""Stateful resources: tables, the blob bucket and the job queues.

Every one of them is deleted with the stack, so a destroy leaves nothing
billable behind.
"""

import aws_cdk
from aws_cdk import aws_dynamodb
from aws_cdk import aws_s3
from aws_cdk import aws_sqs
import constructs

from docintel_infra import config

# Key and index names the service's DynamoDB adapters read and write.
OCCURRENCES_INDEX = "documents"
JOBS_INDEX = "status"


class Data(constructs.Construct):
    """The service's tables, blob bucket, job queue and dead-letter queue.

    Attributes:
        occurrences: Name occurrence table.
        jobs: Job table.
        blobs: Bucket for job inputs and results.
        queue: Work queue.
        dead_letters: Dead-letter queue.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        jobs: config.JobSettings,
    ) -> None:
        """Creates the resources.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            jobs: Queue sizing.
        """
        super().__init__(scope, construct_id)
        destroy = aws_cdk.RemovalPolicy.DESTROY
        text = aws_dynamodb.AttributeType.STRING

        self.occurrences = aws_dynamodb.Table(
            self,
            "Occurrences",
            partition_key=aws_dynamodb.Attribute(name="PK", type=text),
            sort_key=aws_dynamodb.Attribute(name="SK", type=text),
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=destroy,
        )
        self.occurrences.add_global_secondary_index(
            index_name=OCCURRENCES_INDEX,
            partition_key=aws_dynamodb.Attribute(name="gsi1pk", type=text),
            sort_key=aws_dynamodb.Attribute(name="gsi1sk", type=text),
            projection_type=aws_dynamodb.ProjectionType.KEYS_ONLY,
        )

        self.jobs = aws_dynamodb.Table(
            self,
            "Jobs",
            partition_key=aws_dynamodb.Attribute(name="PK", type=text),
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=destroy,
        )
        self.jobs.add_global_secondary_index(
            index_name=JOBS_INDEX,
            partition_key=aws_dynamodb.Attribute(name="status", type=text),
            sort_key=aws_dynamodb.Attribute(name="updated_at", type=text),
            projection_type=aws_dynamodb.ProjectionType.ALL,
        )

        self.blobs = aws_s3.Bucket(
            self,
            "Blobs",
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=destroy,
            auto_delete_objects=True,
        )

        self.dead_letters = aws_sqs.Queue(
            self,
            "DeadLetters",
            retention_period=aws_cdk.Duration.days(
                jobs.dead_letter_retention_days
            ),
            enforce_ssl=True,
            removal_policy=destroy,
        )
        # The worker dead-letters jobs itself; the redrive only catches
        # messages whose worker crashed repeatedly before settling them.
        self.queue = aws_sqs.Queue(
            self,
            "JobQueue",
            visibility_timeout=aws_cdk.Duration.seconds(
                jobs.visibility_timeout_s
            ),
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                queue=self.dead_letters,
                max_receive_count=jobs.max_attempts + 2,
            ),
            enforce_ssl=True,
            removal_policy=destroy,
        )
