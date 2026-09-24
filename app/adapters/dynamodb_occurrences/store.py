"""Occurrence store on one DynamoDB table with conditional writes.

Items of a document share the partition ``DOC#{document id}``: the header
(``HEAD``), one seal per generation (``META#{generation}``) and one item per
occurrence (``OCC#{generation}#{ordinal}``). Keys hold ids only, never names
or filenames. A sparse index over the headers lists the documents.
"""

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Callable
from collections.abc import Sequence
from typing import Any

from app import config
from app.adapters.dynamodb_common import client as dynamodb
from app.domain import errors
from app.domain import extraction
from app.domain import ids
from app.domain import occurrences
from app.ports import occurrence_store

BATCH_SIZE = 25
DOCUMENTS_INDEX = "documents"
DOCUMENTS_PARTITION = "DOCS"
_CONDITION_FAILED = "ConditionalCheckFailedException"


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
        self._table = settings.table
        self._page = {"Limit": page_limit} if page_limit else {}

    async def ensure_table(self) -> None:
        """Creates the table and its document index if they are missing.

        Raises:
            errors.OccurrenceStoreUnavailableError: If the table cannot be
                described or created.
        """
        try:
            await self._call(self._client.describe_table, TableName=self._table)
            return
        except errors.OccurrenceStoreUnavailableError as exc:
            if not dynamodb.has_code(
                exc.__cause__, "ResourceNotFoundException"
            ):
                raise
        strings = [
            {"AttributeName": name, "AttributeType": "S"}
            for name in ("PK", "SK", "gsi1pk", "gsi1sk")
        ]
        await self._call(
            self._client.create_table,
            TableName=self._table,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=strings,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": DOCUMENTS_INDEX,
                    "KeySchema": [
                        {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                        {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
        )
        waiter = self._client.get_waiter("table_exists")
        await asyncio.to_thread(waiter.wait, TableName=self._table)

    async def allocate_order(self, document_key: str) -> int:
        """Increments the document's order counter atomically.

        Args:
            document_key: The document.

        Returns:
            The new order.
        """
        response = await self._call(
            self._client.update_item,
            TableName=self._table,
            Key=_key(document_key, "HEAD"),
            UpdateExpression=(
                "SET document_key = if_not_exists(document_key, :k), "
                "gsi1pk = :p, gsi1sk = :s ADD next_order :one"
            ),
            ExpressionAttributeValues=dynamodb.encode(
                {
                    ":k": document_key,
                    ":p": DOCUMENTS_PARTITION,
                    ":s": _partition(document_key),
                    ":one": 1,
                }
            ),
            ReturnValues="UPDATED_NEW",
        )
        return int(dynamodb.decode(response["Attributes"])["next_order"])

    async def head(self, document_key: str) -> occurrences.DocumentHead:
        """Reads the document's current generation, consistently.

        Args:
            document_key: The document.

        Returns:
            The head.
        """
        response = await self._call(
            self._client.get_item,
            TableName=self._table,
            Key=_key(document_key, "HEAD"),
            ConsistentRead=True,
        )
        current = dynamodb.decode(response.get("Item", {})).get("current")
        manifest = _manifest(current) if current else None
        return occurrences.DocumentHead(document_key, manifest)

    async def write_generation(
        self,
        manifest: occurrences.GenerationManifest,
        items: Sequence[occurrences.StoredOccurrence],
    ) -> None:
        """Writes the occurrences in batches of 25, then the seal.

        Unprocessed items are resent with a doubling backoff; the seal is
        written only once every item is stored.

        Args:
            manifest: The seal.
            items: The occurrences.

        Raises:
            errors.OccurrenceStoreUnavailableError: If items remain
                unprocessed after the batch budget.
        """
        requests = [
            {"PutRequest": {"Item": dynamodb.encode(_occurrence_item(item))}}
            for item in items
        ]
        for start in range(0, len(requests), BATCH_SIZE):
            pending = requests[start : start + BATCH_SIZE]
            for attempt in range(self._settings.batch_max_attempts):
                if attempt:
                    delay = self._settings.batch_backoff_s * 2 ** (attempt - 1)
                    await asyncio.sleep(delay)
                response = await self._call(
                    self._client.batch_write_item,
                    RequestItems={self._table: pending},
                )
                pending = response.get("UnprocessedItems", {}).get(
                    self._table, []
                )
                if not pending:
                    break
            if pending:
                raise errors.OccurrenceStoreUnavailableError(
                    f"{len(pending)} occurrences stayed unprocessed."
                )
        seal = {
            **_key(manifest.document_key, f"META#{manifest.generation}"),
            **dynamodb.encode(_manifest_fields(manifest)),
        }
        await self._call(
            self._client.put_item,
            TableName=self._table,
            Item=seal,
            ConditionExpression="attribute_not_exists(SK)",
        )

    async def promote(
        self, manifest: occurrences.GenerationManifest
    ) -> occurrences.PromoteOutcome:
        """Makes a sealed generation current if its order is higher.

        Args:
            manifest: The sealed generation.

        Returns:
            The outcome.

        Raises:
            errors.OccurrenceStoreUnavailableError: If the update fails for
                another reason than a higher current order.
        """
        try:
            await self._call(
                self._client.update_item,
                TableName=self._table,
                Key=_key(manifest.document_key, "HEAD"),
                UpdateExpression=(
                    "SET document_key = :k, gsi1pk = :p, gsi1sk = :s, "
                    "current_order = :o, #current = :m"
                ),
                ConditionExpression=(
                    "attribute_not_exists(current_order) OR current_order < :o"
                ),
                ExpressionAttributeNames={"#current": "current"},
                ExpressionAttributeValues=dynamodb.encode(
                    {
                        ":k": manifest.document_key,
                        ":p": DOCUMENTS_PARTITION,
                        ":s": _partition(manifest.document_key),
                        ":o": manifest.order,
                        ":m": _manifest_fields(manifest),
                    }
                ),
            )
        except errors.OccurrenceStoreUnavailableError as exc:
            if dynamodb.has_code(exc.__cause__, _CONDITION_FAILED):
                return occurrences.PromoteOutcome.SUPERSEDED
            raise
        return occurrences.PromoteOutcome.CURRENT

    async def documents(self) -> AsyncIterator[occurrences.DocumentHead]:
        """Lists every document with a current generation.

        The index is eventually consistent, so a document promoted a moment
        ago may be missing; each listed head is then read consistently.

        Yields:
            The heads.
        """
        query = {
            "TableName": self._table,
            "IndexName": DOCUMENTS_INDEX,
            "KeyConditionExpression": "gsi1pk = :p",
            "ExpressionAttributeValues": dynamodb.encode(
                {":p": DOCUMENTS_PARTITION}
            ),
        }
        async for row in self._pages(query):
            response = await self._call(
                self._client.get_item,
                TableName=self._table,
                Key=dynamodb.encode({"PK": row["PK"], "SK": "HEAD"}),
                ConsistentRead=True,
            )
            header = dynamodb.decode(response.get("Item", {}))
            if header.get("current"):
                yield occurrences.DocumentHead(
                    str(header["document_key"]), _manifest(header["current"])
                )

    async def current(
        self, head: occurrences.DocumentHead
    ) -> AsyncIterator[occurrences.StoredOccurrence]:
        """Reads the occurrences of a document's current generation.

        Args:
            head: The document's head.

        Yields:
            The occurrences in ordinal order.
        """
        if head.manifest is None:
            return
        prefix = f"OCC#{head.manifest.generation}#"
        query = self._items_of(head.document_key, prefix)
        async for row in self._pages(query):
            yield _occurrence(row)

    async def history(
        self, document_key: str
    ) -> list[occurrences.GenerationManifest]:
        """Lists the sealed generations of a document.

        Args:
            document_key: The document.

        Returns:
            The manifests, oldest order first.
        """
        query = self._items_of(document_key, "META#")
        rows = [row async for row in self._pages(query)]
        return sorted((_manifest(row) for row in rows), key=lambda m: m.order)

    def _items_of(self, document_key: str, prefix: str) -> dict[str, Any]:
        """Builds a consistent query of a document's items by key prefix.

        Args:
            document_key: The document.
            prefix: Sort key prefix.

        Returns:
            The query parameters.
        """
        return {
            "TableName": self._table,
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :prefix)",
            "ExpressionAttributeValues": dynamodb.encode(
                {":pk": _partition(document_key), ":prefix": prefix}
            ),
            "ConsistentRead": True,
        }

    async def _pages(
        self, query: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        """Runs a query across every page.

        Args:
            query: Query parameters without pagination.

        Yields:
            The decoded items, in sort key order.
        """
        start: dict[str, Any] = {}
        while True:
            response = await self._call(
                self._client.query, **query, **self._page, **start
            )
            for item in response.get("Items", []):
                yield dynamodb.decode(item)
            if "LastEvaluatedKey" not in response:
                return
            start = {"ExclusiveStartKey": response["LastEvaluatedKey"]}

    async def _call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Runs a blocking client call off the event loop.

        Args:
            method: The boto3 client method.
            **kwargs: Its parameters.

        Returns:
            The response.
        """
        return await dynamodb.call(
            method, errors.OccurrenceStoreUnavailableError, **kwargs
        )


def _partition(document_key: str) -> str:
    """Returns a document's partition key, built from its id.

    Args:
        document_key: The document.

    Returns:
        ``DOC#{document id}``.
    """
    return f"DOC#{ids.document_id(document_key)}"


def _key(document_key: str, sort_key: str) -> dict[str, Any]:
    """Builds the primary key of a document's item.

    Args:
        document_key: The document.
        sort_key: The item's sort key.

    Returns:
        The encoded key.
    """
    return dynamodb.encode({"PK": _partition(document_key), "SK": sort_key})


def _occurrence_item(item: occurrences.StoredOccurrence) -> dict[str, Any]:
    """Lays out an occurrence as a table item.

    Args:
        item: The occurrence.

    Returns:
        The attributes, keys included.
    """
    return {
        "PK": _partition(item.document_key),
        "SK": f"OCC#{item.generation}#{item.ordinal:06d}",
        "occurrence_id": item.occurrence_id,
        "document_key": item.document_key,
        "content_hash": item.content_hash,
        "generation": item.generation,
        "ordinal": item.ordinal,
        "name": item.name,
        "normalized_name": item.normalized_name,
        "page_number": item.page_number,
        "x": item.box.x,
        "y": item.box.y,
        "width": item.box.width,
        "height": item.box.height,
    }


def _occurrence(row: dict[str, Any]) -> occurrences.StoredOccurrence:
    """Reads an occurrence back from its item.

    Args:
        row: The decoded item.

    Returns:
        The occurrence.
    """
    return occurrences.StoredOccurrence(
        occurrence_id=str(row["occurrence_id"]),
        document_key=str(row["document_key"]),
        content_hash=str(row["content_hash"]),
        generation=str(row["generation"]),
        ordinal=int(row["ordinal"]),
        name=str(row["name"]),
        normalized_name=str(row["normalized_name"]),
        page_number=int(row["page_number"]),
        box=extraction.Box(
            float(row["x"]),
            float(row["y"]),
            float(row["width"]),
            float(row["height"]),
        ),
    )


def _manifest_fields(
    manifest: occurrences.GenerationManifest,
) -> dict[str, Any]:
    """Lays out a manifest as item attributes.

    Args:
        manifest: The manifest.

    Returns:
        The attributes.
    """
    return {
        "document_key": manifest.document_key,
        "generation": manifest.generation,
        "order": manifest.order,
        "content_hash": manifest.content_hash,
        "extractor": manifest.extractor,
        "occurrence_count": manifest.occurrence_count,
        "source": manifest.source,
        "job_id": manifest.job_id,
    }


def _manifest(row: dict[str, Any]) -> occurrences.GenerationManifest:
    """Reads a manifest back from its attributes.

    Args:
        row: The decoded attributes.

    Returns:
        The manifest.
    """
    source: occurrences.Source = "job" if row["source"] == "job" else "sync"
    return occurrences.GenerationManifest(
        document_key=str(row["document_key"]),
        generation=str(row["generation"]),
        order=int(row["order"]),
        content_hash=str(row["content_hash"]),
        extractor=str(row["extractor"]),
        occurrence_count=int(row["occurrence_count"]),
        source=source,
        job_id=None if row.get("job_id") is None else str(row["job_id"]),
    )
