"""DynamoDB batching: unprocessed items are resent before the seal."""

import boto3
from botocore import stub
import pytest

from app import config
from app.adapters.dynamodb_occurrences import store as dynamodb_store
from app.domain import errors
from app.domain import extraction
from app.domain import occurrences

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="adapter not built"
)

TABLE = "occurrences-test"
MANIFEST = occurrences.GenerationManifest(
    "memo.pdf", "g1", 1, "h1", "extractor", 2, "sync"
)
ITEMS = [
    occurrences.StoredOccurrence(
        f"id-{n}",
        "memo.pdf",
        "h1",
        "g1",
        n,
        name,
        name.lower(),
        0,
        extraction.Box(1.0, 2.0, 3.0, 4.0),
    )
    for n, name in enumerate(["Anna Berg", "Lucas Moreau"])
]
LEFT_OVER = {"PutRequest": {"Item": {"PK": {"S": "DOC#x"}, "SK": {"S": "y"}}}}


Store = dynamodb_store.DynamoDbOccurrenceStore


def stubbed(attempts: int) -> tuple[Store, stub.Stubber]:
    """Builds the store on a stubbed client that never reaches AWS.

    Args:
        attempts: Batch writes allowed per generation.

    Returns:
        The store and the stubber to script responses on.
    """
    client = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    settings = config.OccurrenceSettings(
        table=TABLE, batch_max_attempts=attempts, batch_backoff_s=0
    )
    return Store(client, settings), stub.Stubber(client)


async def test_unprocessed_items_are_resent_before_the_seal() -> None:
    store, stubber = stubbed(attempts=3)
    stubber.add_response(
        "batch_write_item",
        {"UnprocessedItems": {TABLE: [LEFT_OVER]}},
        {"RequestItems": {TABLE: [stub.ANY, stub.ANY]}},
    )
    stubber.add_response(
        "batch_write_item",
        {"UnprocessedItems": {}},
        {"RequestItems": {TABLE: [LEFT_OVER]}},
    )
    stubber.add_response("put_item", {})

    with stubber:
        await store.write_generation(MANIFEST, ITEMS)

    stubber.assert_no_pending_responses()


async def test_items_left_after_the_budget_fail_without_a_seal() -> None:
    store, stubber = stubbed(attempts=2)
    for _ in range(2):
        stubber.add_response(
            "batch_write_item", {"UnprocessedItems": {TABLE: [LEFT_OVER]}}
        )
    seals: list[str] = []
    stubber.client.meta.events.register(
        "provide-client-params.dynamodb.PutItem",
        lambda **_: seals.append("put_item"),
    )

    with stubber, pytest.raises(errors.OccurrenceStoreUnavailableError):
        await store.write_generation(MANIFEST, ITEMS)

    assert seals == []
    stubber.assert_no_pending_responses()
