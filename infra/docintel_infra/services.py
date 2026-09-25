"""Fargate services: Qdrant and the job worker."""

from collections.abc import Mapping

import aws_cdk
from aws_cdk import aws_ec2
from aws_cdk import aws_ecs
from aws_cdk import aws_logs
from aws_cdk import aws_servicediscovery
import constructs

from docintel_infra import config

QDRANT_PORT = 6333
# The Qdrant image has bash but neither curl nor wget.
_QDRANT_READY = (
    "bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333 && "
    'printf "GET /readyz HTTP/1.0\\r\\n\\r\\n" >&3 && '
    "head -1 <&3 | grep -q 200'"
)


def log_driver(scope: constructs.Construct, name: str) -> aws_ecs.LogDriver:
    """Sends a container's output to a log group deleted with the stack.

    Args:
        scope: Construct that owns the log group.
        name: Stream prefix and log group id.

    Returns:
        The log driver.
    """
    group = aws_logs.LogGroup(
        scope,
        f"{name}Logs",
        retention=aws_logs.RetentionDays.ONE_WEEK,
        removal_policy=aws_cdk.RemovalPolicy.DESTROY,
    )
    return aws_ecs.LogDrivers.aws_logs(stream_prefix=name, log_group=group)


class Qdrant(constructs.Construct):
    """One Qdrant task on its own disk, reachable only inside the VPC.

    Attributes:
        security_group: Guards the Qdrant port.
        url: HTTP URL clients in the VPC use.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        cluster: aws_ecs.Cluster,
        namespace: aws_servicediscovery.PrivateDnsNamespace,
        settings: config.QdrantSettings,
    ) -> None:
        """Creates the task and its service.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            cluster: Cluster to run in.
            namespace: Namespace the task registers its name in.
            settings: Image and sizing.
        """
        super().__init__(scope, construct_id)
        task = aws_ecs.FargateTaskDefinition(
            self, "Task", cpu=settings.cpu, memory_limit_mib=settings.memory_mb
        )
        container = task.add_container(
            "qdrant",
            image=aws_ecs.ContainerImage.from_registry(settings.image),
            logging=log_driver(self, "Qdrant"),
            port_mappings=[aws_ecs.PortMapping(container_port=QDRANT_PORT)],
            health_check=aws_ecs.HealthCheck(
                command=["CMD-SHELL", _QDRANT_READY],
                start_period=aws_cdk.Duration.seconds(30),
            ),
        )
        container.add_ulimits(
            aws_ecs.Ulimit(
                name=aws_ecs.UlimitName.NOFILE,
                soft_limit=10000,
                hard_limit=10000,
            )
        )
        self.security_group = aws_ec2.SecurityGroup(
            self, "SecurityGroup", vpc=cluster.vpc, allow_all_outbound=True
        )
        # Task storage is local to the task: stopping the old task before
        # starting a new one keeps two Qdrant processes off one data set.
        aws_ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task,
            desired_count=1,
            min_healthy_percent=0,
            max_healthy_percent=100,
            circuit_breaker=aws_ecs.DeploymentCircuitBreaker(rollback=False),
            security_groups=[self.security_group],
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            cloud_map_options=aws_ecs.CloudMapOptions(
                name=settings.service_name,
                cloud_map_namespace=namespace,
                dns_record_type=aws_servicediscovery.DnsRecordType.A,
                dns_ttl=aws_cdk.Duration.seconds(10),
            ),
        )
        self.url = (
            f"http://{settings.service_name}.{settings.namespace}:{QDRANT_PORT}"
        )

    def allow_from(self, peer: aws_ec2.ISecurityGroup) -> None:
        """Opens the Qdrant port to one security group.

        Args:
            peer: The clients' security group.
        """
        self.security_group.add_ingress_rule(
            peer, aws_ec2.Port.tcp(QDRANT_PORT), "Qdrant clients"
        )


class Worker(constructs.Construct):
    """The job worker process, unchanged, as one Fargate task.

    Attributes:
        security_group: The worker's security group.
        task_role: Role the worker's AWS calls use.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        cluster: aws_ecs.Cluster,
        image: aws_ecs.ContainerImage,
        environment: Mapping[str, str],
        settings: config.WorkerSettings,
    ) -> None:
        """Creates the task and its service.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            cluster: Cluster to run in.
            image: The service image.
            environment: Service settings as environment variables.
            settings: Sizing.
        """
        super().__init__(scope, construct_id)
        task = aws_ecs.FargateTaskDefinition(
            self, "Task", cpu=settings.cpu, memory_limit_mib=settings.memory_mb
        )
        task.add_container(
            "worker",
            image=image,
            command=["python", "-m", "app.worker_main"],
            environment=dict(environment),
            logging=log_driver(self, "Worker"),
        )
        self.task_role = task.task_role
        self.security_group = aws_ec2.SecurityGroup(
            self, "SecurityGroup", vpc=cluster.vpc, allow_all_outbound=True
        )
        aws_ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task,
            desired_count=1,
            # A second worker during a deploy is safe: claims are conditional.
            min_healthy_percent=100,
            circuit_breaker=aws_ecs.DeploymentCircuitBreaker(rollback=False),
            security_groups=[self.security_group],
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )
