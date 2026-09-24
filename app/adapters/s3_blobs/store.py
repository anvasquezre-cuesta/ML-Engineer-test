"""Blob store on S3; locally any S3-compatible endpoint such as SeaweedFS."""

from typing import Any

from app import config
from app.ports import blob_store


def build_client(settings: config.BlobSettings) -> Any:
    """Builds an S3 client with explicit credentials and timeouts.

    A custom endpoint uses path-style addressing; without keys the client
    uses the default chain, i.e. the task role.

    Args:
        settings: Endpoint, region, credentials and limits.

    Returns:
        The boto3 S3 client.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


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

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def get(self, key: str) -> bytes | None:
        """Reads an object.

        Args:
            key: Object key.

        Returns:
            The content, or ``None`` if there is no such object.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """Deletes an object if it exists.

        Args:
            key: Object key.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
