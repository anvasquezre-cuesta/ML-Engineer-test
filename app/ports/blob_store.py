"""Port for storing staged uploads and job results as binary objects."""

import abc


class BlobStore(abc.ABC):
    """Key-value object storage.

    Every method may raise ``BlobStoreUnavailableError``.
    """

    @abc.abstractmethod
    async def put(self, key: str, data: bytes) -> None:
        """Stores ``data`` under ``key``, replacing any existing object.

        Args:
            key: Object key.
            data: Object content.
        """

    @abc.abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Reads the object stored under ``key``.

        Args:
            key: Object key.

        Returns:
            The object content, or ``None`` if there is no such object.
        """

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Deletes the object stored under ``key`` if it exists.

        Args:
            key: Object key.
        """
