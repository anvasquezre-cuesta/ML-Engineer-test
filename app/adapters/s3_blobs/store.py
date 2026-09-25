"""Blob store on S3; locally any S3-compatible endpoint such as SeaweedFS."""

import asyncio
from collections.abc import Callable
import functools
from typing import Any

import boto3
from botocore import config as botocore_config
from botocore import exceptions

from app import config
from app.domain import errors
from app.ports import blob_store

_MISSING = frozenset({"NoSuchKey", "404"})


def build_client(settings: config.BlobSettings) -> Any:
    """Builds an S3 client with explicit credentials and timeouts.

    A custom endpoint uses path-style addressing; without keys the client
    uses the default chain, i.e. the task role.

    Args:
        settings: Endpoint, region, credentials and limits.

    Returns:
        The boto3 S3 client.
    """
    key_id: str | None = None
    secret: str | None = None
    if settings.access_key_id and settings.secret_access_key:
        key_id = settings.access_key_id.get_secret_value()
        secret = settings.secret_access_key.get_secret_value()
    return boto3.client(
        "s3",
        region_name=settings.region,
        endpoint_url=settings.endpoint_url or None,
        config=botocore_config.Config(
            s3=(
                {"addressing_style": "path"} if settings.endpoint_url else None
            ),
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


class S3BlobStore(blob_store.BlobStore):
    """Stores objects in one bucket; never creates the bucket."""

    def __init__(self, client: Any, bucket: str) -> None:
        """Initializes the store.

        Args:
            client: The boto3 S3 client.
            bucket: The bucket, created by the infrastructure.
        """
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        """Stores ``data`` under ``key``.

        Args:
            key: Object key.
            data: Content.
        """
        await self._call(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data
        )

    async def get(self, key: str) -> bytes | None:
        """Reads an object.

        Args:
            key: Object key.

        Returns:
            The content, or ``None`` if there is no such object.

        Raises:
            errors.BlobStoreUnavailableError: If the read fails for any other
                reason, including rejected credentials.
        """
        try:
            response = await self._call(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except errors.BlobStoreUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, exceptions.ClientError):
                code = cause.response.get("Error", {}).get("Code")
                if code in _MISSING:
                    return None
            raise
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        """Deletes an object if it exists.

        Args:
            key: Object key.
        """
        await self._call(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )

    async def _call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Runs a blocking client call off the event loop.

        Args:
            method: The boto3 client method.
            **kwargs: Its parameters.

        Returns:
            The response.

        Raises:
            errors.BlobStoreUnavailableError: If the call fails; the botocore
                error is kept as its cause.
        """
        try:
            return await asyncio.to_thread(functools.partial(method, **kwargs))
        except (exceptions.BotoCoreError, exceptions.ClientError) as exc:
            raise errors.BlobStoreUnavailableError() from exc
