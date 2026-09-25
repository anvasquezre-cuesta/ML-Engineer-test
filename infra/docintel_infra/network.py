"""VPC, ECS cluster and the private DNS namespace services register in."""

import aws_cdk
from aws_cdk import aws_ec2
from aws_cdk import aws_ecs
from aws_cdk import aws_servicediscovery
import constructs


class Network(constructs.Construct):
    """Two AZs of public and private subnets with one NAT gateway.

    The NAT carries Bedrock, ECR, Docker Hub and log traffic; S3 and
    DynamoDB go through free gateway endpoints instead.

    Attributes:
        vpc: The VPC.
        cluster: ECS cluster for the Qdrant and worker tasks.
        namespace: Private DNS namespace inside the VPC.
    """

    def __init__(
        self, scope: constructs.Construct, construct_id: str, namespace: str
    ) -> None:
        """Creates the network.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            namespace: Name of the private DNS namespace.
        """
        super().__init__(scope, construct_id)
        self.vpc = aws_ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                aws_ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=aws_ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                aws_ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
            gateway_endpoints={
                "S3": aws_ec2.GatewayVpcEndpointOptions(
                    service=aws_ec2.GatewayVpcEndpointAwsService.S3
                ),
                "DynamoDb": aws_ec2.GatewayVpcEndpointOptions(
                    service=aws_ec2.GatewayVpcEndpointAwsService.DYNAMODB
                ),
            },
        )
        self.cluster = aws_ecs.Cluster(self, "Cluster", vpc=self.vpc)
        self.namespace = aws_servicediscovery.PrivateDnsNamespace(
            self, "Namespace", name=namespace, vpc=self.vpc
        )
        self.namespace.apply_removal_policy(aws_cdk.RemovalPolicy.DESTROY)
