"""Occurrence store on one DynamoDB table with conditional writes.

Items of a document share the partition ``DOC#{document id}``: the header
(``HEAD``), one seal per generation (``META#{generation}``) and one item per
occurrence (``OCC#{generation}#{ordinal}``). Keys hold ids only, never names
or filenames. A sparse index over the headers lists the documents.
"""

from collections.abc import AsyncIterator
from collections.abc import Sequence
from typing import Any

from app import config
from app.domain import occurrences
from app.ports import occurrence_store


def build_client(settings: config.DynamoDbSettings) -> Any:
    """Builds a DynamoDB client with explicit credentials and timeouts.

    Args:
        settings: Endpoint, region, credentials and limits.

    Returns:
        The boto3 DynamoDB client.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


class DynamoDbOccurrenceStore(
    occurrence_store.OccurrenceWriter, occurrence_store.OccurrenceReader
):
    """Occurrence store whose promotions are conditional updates."""

    def __init__(
        self,
        client: Any,
        settings: config.OccurrenceSettings,
        page_limit: int | None = None,
    ) -> None:
        """Initializes the store.

        Args:
            client: The boto3 DynamoDB client.
            settings: Table name and batch retry budget.
            page_limit: Items per query page; ``None`` uses DynamoDB's.
        """
        self._client = client
        self._settings = settings
        self._page_limit = page_limit

    async def ensure_table(self) -> None:
        """Creates the table and its document index if they are missing.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def allocate_order(self, document_key: str) -> int:
        """Reserves the next acceptance order of a document.

        Args:
            document_key: The document.

        Returns:
            The new order.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def head(self, document_key: str) -> occurrences.DocumentHead:
        """Reads the document's current generation, consistently.

        Args:
            document_key: The document.

        Returns:
            The head.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def write_generation(
        self,
        manifest: occurrences.GenerationManifest,
        items: Sequence[occurrences.StoredOccurrence],
    ) -> None:
        """Writes the occurrences in batches, then the seal.

        Args:
            manifest: The seal.
            items: The occurrences.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def promote(
        self, manifest: occurrences.GenerationManifest
    ) -> occurrences.PromoteOutcome:
        """Makes a sealed generation current if its order is higher.

        Args:
            manifest: The sealed generation.

        Returns:
            The outcome.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    def documents(self) -> AsyncIterator[occurrences.DocumentHead]:
        """Lists every document with a current generation.

        Returns:
            The heads.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    def current(
        self, head: occurrences.DocumentHead
    ) -> AsyncIterator[occurrences.StoredOccurrence]:
        """Reads the occurrences of a document's current generation.

        Args:
            head: The document's head.

        Returns:
            The occurrences in ordinal order.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def history(
        self, document_key: str
    ) -> list[occurrences.GenerationManifest]:
        """Lists the sealed generations of a document.

        Args:
            document_key: The document.

        Returns:
            The manifests, oldest order first.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
