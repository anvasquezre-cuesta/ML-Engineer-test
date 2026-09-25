"""The API: the service image on Lambda behind an API Gateway HTTP API."""

from collections.abc import Mapping

import aws_cdk
from aws_cdk import aws_apigatewayv2
from aws_cdk import aws_apigatewayv2_integrations
from aws_cdk import aws_ec2
from aws_cdk import aws_iam
from aws_cdk import aws_lambda
from aws_cdk import aws_logs
import constructs

from docintel_infra import config


class Api(constructs.Construct):
    """The unchanged FastAPI app, run by the Lambda Web Adapter.

    Attributes:
        function: The Lambda function.
        security_group: The function's security group.
        http_api: The HTTP API in front of it.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        vpc: aws_ec2.IVpc,
        code: aws_lambda.DockerImageCode,
        environment: Mapping[str, str],
        settings: config.ApiSettings,
    ) -> None:
        """Creates the function and the HTTP API.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            vpc: VPC whose private subnets reach Qdrant.
            code: The Lambda image.
            environment: Service settings as environment variables.
            settings: Memory, timeout and request limits.
        """
        super().__init__(scope, construct_id)
        self.security_group = aws_ec2.SecurityGroup(
            self, "SecurityGroup", vpc=vpc, allow_all_outbound=True
        )
        self.function = aws_lambda.DockerImageFunction(
            self,
            "Function",
            code=code,
            architecture=aws_lambda.Architecture.X86_64,
            memory_size=settings.memory_mb,
            timeout=aws_cdk.Duration.seconds(settings.timeout_s),
            environment=dict(environment),
            vpc=vpc,
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[self.security_group],
            log_group=aws_logs.LogGroup(
                self,
                "Logs",
                retention=aws_logs.RetentionDays.ONE_WEEK,
                removal_policy=aws_cdk.RemovalPolicy.DESTROY,
            ),
        )
        # Loading the models from the lazily fetched image takes about a
        # minute, so traffic goes to environments initialized in advance.
        live = aws_lambda.Alias(
            self,
            "Live",
            alias_name="live",
            version=self.function.current_version,
            provisioned_concurrent_executions=settings.provisioned_concurrency,
        )
        self.http_api = aws_apigatewayv2.HttpApi(
            self,
            "HttpApi",
            default_integration=aws_apigatewayv2_integrations.HttpLambdaIntegration(
                "Service", live
            ),
        )

    def allow_bedrock(self, llm: config.LlmSettings) -> None:
        """Lets the function invoke the model through its inference profile.

        A cross-region profile needs the profile itself and the model in
        every region the profile may route a request to.

        Args:
            llm: The profile, model and routed regions.
        """
        stack = aws_cdk.Stack.of(self)
        profile = stack.format_arn(
            service="bedrock",
            resource="inference-profile",
            resource_name=llm.inference_profile,
        )
        models = [
            f"arn:{stack.partition}:bedrock:{region}::foundation-model/"
            f"{llm.foundation_model}"
            for region in llm.model_regions
        ]
        self.function.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[profile, *models],
            )
        )
