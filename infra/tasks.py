"""Infrastructure tasks run with ``uv run invoke <task>`` inside ``infra/``.

The CDK CLI gets the deploy credentials from the settings explicitly, as
fixed values on its own subprocess.
"""

import json
import pathlib
from typing import Any

from invoke import collection
from invoke import context
from invoke import exceptions
from invoke import tasks

from docintel_infra import config

PYTHON_PATHS = "app.py tasks.py docintel_infra tests"
PYTHON_FILES = " ".join(
    str(path)
    for pattern in ("*.py", "docintel_infra/*.py", "tests/*.py")
    for path in sorted(pathlib.Path().glob(pattern))
)


def _credentials() -> dict[str, str]:
    """Returns the deploy credentials as environment for a CLI subprocess.

    Returns:
        The AWS variables.

    Raises:
        exceptions.Exit: If the deploy credentials are not configured.
    """
    settings = config.InfraSettings()
    if not (settings.aws_access_key_id and settings.aws_secret_access_key):
        raise exceptions.Exit("Set the AWS keys in .env first.", code=1)
    secret = settings.aws_secret_access_key.get_secret_value()
    return {
        "AWS_ACCESS_KEY_ID": settings.aws_access_key_id.get_secret_value(),
        "AWS_SECRET_ACCESS_KEY": secret,
        "AWS_REGION": settings.region,
        "AWS_DEFAULT_REGION": settings.region,
    }


def _aws(c: context.Context, command: str) -> Any:
    """Runs an AWS CLI command and parses its JSON output.

    Args:
        c: Invoke context.
        command: AWS CLI arguments.

    Returns:
        The parsed output, or ``None`` if the command failed.
    """
    result = c.run(
        f"aws {command} --output json",
        env=_credentials(),
        hide=True,
        warn=True,
    )
    if result is None or not result.ok:
        return None
    return json.loads(result.stdout or "null")


def _stack_assets() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Lists the images and files the last synth published for the stack.

    Returns:
        ECR image and S3 object locations in the CDK bootstrap resources.
    """
    stack = config.InfraSettings().stack_name
    manifest = json.loads(
        pathlib.Path(f"cdk.out/{stack}.assets.json").read_text()
    )
    images = [
        {"repository": d["repositoryName"], "tag": d["imageTag"]}
        for asset in manifest.get("dockerImages", {}).values()
        for d in asset["destinations"].values()
    ]
    files = [
        {"bucket": d["bucketName"], "key": d["objectKey"]}
        for asset in manifest.get("files", {}).values()
        for d in asset["destinations"].values()
    ]
    return images, files


def _account(c: context.Context) -> str:
    """Returns the deploying account id.

    Args:
        c: Invoke context.

    Returns:
        The account id.
    """
    identity = _aws(c, "sts get-caller-identity")
    return str(identity["Account"])


def _orphan_log_groups(c: context.Context) -> list[str]:
    """Lists log groups created at runtime by the stack's helper Lambdas.

    CloudFormation does not own them, so a destroy leaves them behind.

    Args:
        c: Invoke context.

    Returns:
        Their names.
    """
    stack = config.InfraSettings().stack_name
    found = _aws(
        c,
        "logs describe-log-groups "
        f"--log-group-name-prefix /aws/lambda/{stack}-",
    )
    return [g["logGroupName"] for g in (found or {}).get("logGroups", [])]


def _cdk(c: context.Context, command: str) -> None:
    """Runs the pinned CDK CLI with the deploy credentials and region.

    Args:
        c: Invoke context.
        command: CDK CLI arguments.
    """
    settings = config.InfraSettings()
    c.run(
        f"npx --yes aws-cdk@{settings.cdk_cli_version} {command}",
        env=_credentials(),
        pty=True,
    )


@tasks.task
def check(c: context.Context) -> None:
    """Lints, type-checks and tests the CDK app.

    Args:
        c: Invoke context.
    """
    c.run(f"ruff check {PYTHON_PATHS}", pty=True)
    c.run(f"ruff format --check {PYTHON_PATHS}", pty=True)
    c.run(f"pydoclint {PYTHON_PATHS}", pty=True)
    c.run(f"mypy {PYTHON_PATHS}", pty=True)
    # The repository's module-only import rule, with this project on the path.
    c.run(
        "python -c \"import runpy, sys; sys.path.insert(0, '.'); "
        "sys.argv = ['check', *'" + PYTHON_FILES + "'.split()]; "
        "runpy.run_path('../scripts/check_module_imports.py', "
        "run_name='__main__')\"",
        pty=True,
    )
    c.run("pytest", pty=True)


@tasks.task
def synth(c: context.Context) -> None:
    """Synthesizes the stack into ``cdk.out``.

    Args:
        c: Invoke context.
    """
    _cdk(c, "synth --quiet")


@tasks.task
def diff(c: context.Context) -> None:
    """Shows what a deploy would change.

    Args:
        c: Invoke context.
    """
    _cdk(c, "diff")


@tasks.task
def deploy(c: context.Context) -> None:
    """Deploys the stack and writes its outputs to ``cdk.out/outputs.json``.

    Args:
        c: Invoke context.
    """
    _cdk(
        c,
        "deploy --require-approval never --outputs-file cdk.out/outputs.json",
    )


@tasks.task
def clean_assets(c: context.Context) -> None:
    """Deletes what a destroy leaves: the stack's published assets and logs.

    Only the images and files listed in the stack's asset manifest are
    removed from the shared CDK bootstrap repository and bucket.

    Args:
        c: Invoke context.
    """
    images, files = _stack_assets()
    for image in images:
        repository = image["repository"].replace(
            "${AWS::AccountId}", _account(c)
        )
        _aws(
            c,
            f"ecr batch-delete-image --repository-name {repository} "
            f"--image-ids imageTag={image['tag']}",
        )
    for item in files:
        bucket = item["bucket"].replace("${AWS::AccountId}", _account(c))
        _aws(c, f"s3api delete-object --bucket {bucket} --key {item['key']}")
    for group in _orphan_log_groups(c):
        _aws(c, f"logs delete-log-group --log-group-name {group}")
    print(
        f"Removed {len(images)} images, {len(files)} files and the "
        "helper log groups."
    )


@tasks.task
def destroy(c: context.Context) -> None:
    """Deletes the stack, then what CloudFormation leaves behind.

    Args:
        c: Invoke context.
    """
    _cdk(c, "destroy --force")
    clean_assets(c)


@tasks.task
def leftovers(c: context.Context) -> None:
    """Lists anything of the stack that still exists; read-only.

    Args:
        c: Invoke context.

    Raises:
        exceptions.Exit: If anything is left.
    """
    stack = config.InfraSettings().stack_name
    left: list[str] = []
    if _aws(c, f"cloudformation describe-stacks --stack-name {stack}"):
        left.append(f"stack {stack}")
    tagged = _aws(
        c,
        "resourcegroupstaggingapi get-resources --tag-filters "
        f"Key=aws:cloudformation:stack-name,Values={stack}",
    )
    left += [
        r["ResourceARN"]
        for r in (tagged or {}).get("ResourceTagMappingList", [])
    ]
    left += _orphan_log_groups(c)
    images, files = _stack_assets()
    for image in images:
        repository = image["repository"].replace(
            "${AWS::AccountId}", _account(c)
        )
        if _aws(
            c,
            f"ecr describe-images --repository-name {repository} "
            f"--image-ids imageTag={image['tag']}",
        ):
            left.append(f"image {repository}:{image['tag']}")
    for item in files:
        bucket = item["bucket"].replace("${AWS::AccountId}", _account(c))
        if _aws(c, f"s3api head-object --bucket {bucket} --key {item['key']}"):
            left.append(f"s3://{bucket}/{item['key']}")
    for name in left:
        print(f"LEFT: {name}")
    if left:
        raise exceptions.Exit(f"{len(left)} resources left.", code=1)
    print("Nothing of the stack is left.")


@tasks.task
def outputs(c: context.Context) -> None:
    """Prints the deployed URLs.

    Args:
        c: Invoke context.
    """
    path = pathlib.Path("cdk.out/outputs.json")
    for values in json.loads(path.read_text()).values():
        for name, value in values.items():
            print(f"{name}: {value}")


namespace = collection.Collection(
    check, synth, diff, deploy, destroy, clean_assets, leftovers, outputs
)
