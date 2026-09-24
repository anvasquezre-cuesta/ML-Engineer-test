"""DynamoDB client construction, attribute encoding and error handling."""

import asyncio
from collections.abc import Callable
import decimal
import functools
from typing import Any

import boto3
from boto3.dynamodb import types
from botocore import config as botocore_config
from botocore import exceptions

from app import config
from app.domain import errors

_serializer = types.TypeSerializer()
_deserializer = types.TypeDeserializer()


def build_client(settings: config.DynamoDbSettings) -> Any:
    """Builds a DynamoDB client with explicit credentials and timeouts.

    Without keys the client uses the default chain, i.e. the task role.

    Args:
        settings: Endpoint, region, credentials and limits.

    Returns:
        The boto3 DynamoDB client.
    """
    key_id: str | None = None
    secret: str | None = None
    if settings.access_key_id and settings.secret_access_key:
        key_id = settings.access_key_id.get_secret_value()
        secret = settings.secret_access_key.get_secret_value()
    return boto3.client(
        "dynamodb",
        region_name=settings.region,
        endpoint_url=settings.endpoint_url or None,
        config=botocore_config.Config(
            connect_timeout=settings.timeout_s,
            read_timeout=settings.timeout_s,
            retries={
                "total_max_attempts": settings.max_retries + 1,
                "mode": "standard",
            },
        ),
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )


async def call(  # noqa: DOC503
    method: Callable[..., Any],
    unavailable: type[errors.AppError],
    **kwargs: Any,
) -> Any:
    """Runs a blocking client call off the event loop.

    Args:
        method: The boto3 client method.
        unavailable: Domain error raised when the call fails.
        **kwargs: The call's parameters.

    Returns:
        The response.

    Raises:
        errors.AppError: ``unavailable``, with the botocore error as its
            cause.
    """
    try:
        return await asyncio.to_thread(functools.partial(method, **kwargs))
    except (exceptions.BotoCoreError, exceptions.ClientError) as exc:
        raise unavailable() from exc


def has_code(error: BaseException | None, code: str) -> bool:
    """Tells whether a botocore error carries the given error code.

    Args:
        error: The error, if any.
        code: The AWS error code.

    Returns:
        Whether it matches.
    """
    return (
        isinstance(error, exceptions.ClientError)
        and error.response.get("Error", {}).get("Code") == code
    )


def encode_value(value: Any) -> Any:
    """Encodes one value as a DynamoDB attribute value.

    Floats become decimals, which DynamoDB numbers require.

    Args:
        value: A plain value.

    Returns:
        The attribute value.
    """
    if isinstance(value, float):
        value = decimal.Decimal(repr(value))
    elif isinstance(value, dict):
        return {"M": {k: encode_value(v) for k, v in value.items()}}
    elif isinstance(value, list):
        return {"L": [encode_value(v) for v in value]}
    return _serializer.serialize(value)


def encode(values: dict[str, Any]) -> dict[str, Any]:
    """Encodes plain values as DynamoDB attribute values.

    Args:
        values: Plain values by name.

    Returns:
        The attribute values by name.
    """
    return {name: encode_value(value) for name, value in values.items()}


def decode(item: dict[str, Any]) -> dict[str, Any]:
    """Decodes DynamoDB attribute values into plain values.

    Args:
        item: Attribute values by name.

    Returns:
        Plain values by name; numbers stay decimals.
    """
    return {name: _deserializer.deserialize(v) for name, v in item.items()}
