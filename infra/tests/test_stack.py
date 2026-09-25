"""The synthesized stack against the deployment's correctness rules."""

from typing import Any

import aws_cdk
from aws_cdk import assertions
import pytest

from docintel_infra import config
from docintel_infra import stack

Resources = dict[str, dict[str, Any]]


@pytest.fixture(scope="module")
def template() -> assertions.Template:
    """Synthesizes the stack once, without building any asset.

    Returns:
        The CloudFormation template.
    """
    app = aws_cdk.App(context={"aws:cdk:bundling-stacks": []})
    built = stack.DocintelStack(
        app,
        "Test",
        config.InfraSettings(_env_file=None),
        env=aws_cdk.Environment(region="us-east-1"),
    )
    return assertions.Template.from_stack(built)


def of_type(template: assertions.Template, kind: str) -> Resources:
    """Returns the resources of one CloudFormation type.

    Args:
        template: The template.
        kind: Resource type, e.g. ``AWS::SQS::Queue``.

    Returns:
        Logical id to resource.
    """
    return {
        name: dict(resource)
        for name, resource in template.find_resources(kind).items()
    }


def test_nothing_stateful_survives_a_destroy(
    template: assertions.Template,
) -> None:
    kinds = (
        "AWS::DynamoDB::Table",
        "AWS::S3::Bucket",
        "AWS::SQS::Queue",
        "AWS::Logs::LogGroup",
    )
    kept = [
        (kind, name)
        for kind in kinds
        for name, resource in of_type(template, kind).items()
        if resource.get("DeletionPolicy") != "Delete"
    ]
    buckets = of_type(template, "AWS::S3::Bucket")
    emptied = of_type(template, "Custom::S3AutoDeleteObjects")

    assert kept == []
    assert len(emptied) == len(buckets) == 2


def test_tables_have_the_keys_and_indexes_the_service_uses(
    template: assertions.Template,
) -> None:
    def shape(table: dict[str, Any]) -> tuple[Any, ...]:
        properties = table["Properties"]
        keys = [
            (k["AttributeName"], k["KeyType"]) for k in properties["KeySchema"]
        ]
        indexes = [
            (
                index["IndexName"],
                [
                    (k["AttributeName"], k["KeyType"])
                    for k in index["KeySchema"]
                ],
                index["Projection"]["ProjectionType"],
            )
            for index in properties.get("GlobalSecondaryIndexes", [])
        ]
        return keys, indexes

    shapes = sorted(
        shape(t) for t in of_type(template, "AWS::DynamoDB::Table").values()
    )

    assert shapes == [
        (
            [("PK", "HASH")],
            [("status", [("status", "HASH"), ("updated_at", "RANGE")], "ALL")],
        ),
        (
            [("PK", "HASH"), ("SK", "RANGE")],
            [
                (
                    "documents",
                    [("gsi1pk", "HASH"), ("gsi1sk", "RANGE")],
                    "KEYS_ONLY",
                )
            ],
        ),
    ]


def test_crashed_jobs_redrive_only_after_the_worker_gave_up(
    template: assertions.Template,
) -> None:
    settings = config.JobSettings()
    queues = of_type(template, "AWS::SQS::Queue").values()
    [work] = [q for q in queues if "RedrivePolicy" in q["Properties"]]
    properties = work["Properties"]

    assert (
        properties["RedrivePolicy"]["maxReceiveCount"]
        == settings.max_attempts + 2
    )
    assert properties["VisibilityTimeout"] > settings.lease_s


def test_qdrant_is_private_and_never_runs_twice(
    template: assertions.Template,
) -> None:
    ingress = [
        rule
        for rule in of_type(template, "AWS::EC2::SecurityGroupIngress").values()
        if rule["Properties"].get("FromPort") == 6333
    ]
    open_groups = [
        group
        for group in of_type(template, "AWS::EC2::SecurityGroup").values()
        for rule in group["Properties"].get("SecurityGroupIngress", [])
        if rule.get("CidrIp") or rule.get("CidrIpv6")
    ]
    [qdrant] = [
        service
        for service in of_type(template, "AWS::ECS::Service").values()
        if service["Properties"].get("ServiceRegistries")
    ]
    deployment = qdrant["Properties"]["DeploymentConfiguration"]

    assert len(ingress) == 2
    assert all("SourceSecurityGroupId" in r["Properties"] for r in ingress)
    assert open_groups == []
    assert (
        deployment["MinimumHealthyPercent"],
        deployment["MaximumPercent"],
    ) == (0, 100)


def test_api_runs_in_aws_mode_within_the_gateway_limits(
    template: assertions.Template,
) -> None:
    [function] = [
        f
        for f in of_type(template, "AWS::Lambda::Function").values()
        if f["Properties"].get("PackageType") == "Image"
    ]
    variables = function["Properties"]["Environment"]["Variables"]

    assert variables["DOCINTEL_CLOUD_ENV"] == "aws"
    assert (
        int(variables["DOCINTEL_UPLOAD__MAX_BYTES"]) < 6 * 1024 * 1024 * 3 // 4
    )
    assert float(variables["DOCINTEL_LLM__DEADLINE_S"]) < 30
    assert not [
        name for name in variables if "SECRET" in name or "KEY_ID" in name
    ]
    assert "VpcConfig" in function["Properties"]


def test_bedrock_access_is_the_profile_and_its_routed_models_only(
    template: assertions.Template,
) -> None:
    statements = [
        statement
        for policy in of_type(template, "AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        if "bedrock:InvokeModel" in statement["Action"]
    ]
    [statement] = statements
    rendered = str(statement["Resource"])

    assert "inference-profile/us.amazon.nova-lite-v1:0" in rendered
    for region in config.LlmSettings().model_regions:
        assert (
            f"bedrock:{region}::foundation-model/amazon.nova-lite-v1:0"
            in rendered
        )
    assert "*" not in [r for r in statement["Resource"] if isinstance(r, str)]


def test_viewer_sends_api_paths_to_the_gateway_uncached_without_host(
    template: assertions.Template,
) -> None:
    [distribution] = of_type(template, "AWS::CloudFront::Distribution").values()
    behaviours = distribution["Properties"]["DistributionConfig"][
        "CacheBehaviors"
    ]
    caching_disabled = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    all_viewer_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

    assert sorted(b["PathPattern"] for b in behaviours) == ["/api/*", "/health"]
    for behaviour in behaviours:
        assert behaviour["CachePolicyId"] == caching_disabled
        assert behaviour["OriginRequestPolicyId"] == all_viewer_except_host
        assert "POST" in behaviour["AllowedMethods"]


def test_api_traffic_goes_to_environments_initialized_in_advance(
    template: assertions.Template,
) -> None:
    [alias] = of_type(template, "AWS::Lambda::Alias").values()
    [integration] = of_type(template, "AWS::ApiGatewayV2::Integration").values()
    alias_id = next(iter(of_type(template, "AWS::Lambda::Alias")))

    assert (
        alias["Properties"]["ProvisionedConcurrencyConfig"][
            "ProvisionedConcurrentExecutions"
        ]
        >= 1
    )
    assert alias_id in str(integration["Properties"]["IntegrationUri"])
