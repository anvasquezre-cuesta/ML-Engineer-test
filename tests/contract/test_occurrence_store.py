"""The fake and DynamoDB Local honour the same occurrence store contract."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import uuid

import pydantic
import pytest

from app import config
from app.adapters.dynamodb_occurrences import store as dynamodb_store
from app.domain import extraction
from app.domain import occurrences
from tests.fakes import occurrence_store as fake_store

Store = (
    fake_store.InMemoryOccurrenceStore | dynamodb_store.DynamoDbOccurrenceStore
)

KINDS = [
    "fake",
    pytest.param(
        "dynamodb",
        marks=[
            pytest.mark.docker,
            pytest.mark.xfail(
                strict=True, raises=NotImplementedError, reason="not built"
            ),
        ],
    ),
]


@contextlib.asynccontextmanager
async def store_of(kind: str) -> AsyncIterator[Store]:
    """Opens an empty store; DynamoDB Local gets a table of its own.

    Pages hold 7 items, so every read of more than 7 items pages.

    Args:
        kind: ``fake`` or ``dynamodb``.

    Yields:
        The store.
    """
    if kind == "fake":
        yield fake_store.InMemoryOccurrenceStore()
        return
    client = dynamodb_store.build_client(
        config.DynamoDbSettings(
            endpoint_url="http://localhost:8000",
            access_key_id=pydantic.SecretStr("local"),
            secret_access_key=pydantic.SecretStr("local"),
        )
    )
    table = f"occurrences-{uuid.uuid4().hex}"
    store = dynamodb_store.DynamoDbOccurrenceStore(
        client, config.OccurrenceSettings(table=table), page_limit=7
    )
    await store.ensure_table()
    try:
        yield store
    finally:
        client.delete_table(TableName=table)


def generation(
    key: str, order: int, count: int
) -> tuple[occurrences.GenerationManifest, list[occurrences.StoredOccurrence]]:
    """Builds a sealed run of ``count`` occurrences of one document.

    Args:
        key: The document key.
        order: The run's acceptance order.
        count: Occurrences in the run.

    Returns:
        The manifest and its occurrences.
    """
    gen = uuid.uuid4().hex
    items = [
        occurrences.StoredOccurrence(
            f"{gen}-{n}",
            key,
            "h",
            gen,
            n,
            f"Person {n}",
            f"person {n}",
            n % 3,
            extraction.Box(1.5 * n, 2.0, 30.25, 9.0),
        )
        for n in range(count)
    ]
    manifest = occurrences.GenerationManifest(
        key, gen, order, "h", "extractor", count, "sync"
    )
    return manifest, items


async def read_current(
    store: Store, key: str
) -> list[occurrences.StoredOccurrence]:
    """Reads a document's current occurrences.

    Args:
        store: The store.
        key: The document key.

    Returns:
        The occurrences.
    """
    head = await store.head(key)
    return [o async for o in store.current(head)]


@pytest.mark.parametrize("kind", KINDS)
async def test_large_versions_round_trip_in_order_and_stay_apart(
    kind: str,
) -> None:
    async with store_of(kind) as store:
        memo, memo_items = generation("memo.pdf", 1, 60)
        minutes, minutes_items = generation("minutes.pdf", 1, 3)
        for manifest, items in ((memo, memo_items), (minutes, minutes_items)):
            await store.write_generation(manifest, items)
            await store.promote(manifest)

        listed = sorted([h.document_key async for h in store.documents()])
        memo_read = await read_current(store, "memo.pdf")
        minutes_read = await read_current(store, "minutes.pdf")

    assert listed == ["memo.pdf", "minutes.pdf"]
    assert memo_read == memo_items
    assert minutes_read == minutes_items


@pytest.mark.parametrize("kind", KINDS)
async def test_only_a_higher_order_becomes_current(kind: str) -> None:
    async with store_of(kind) as store:
        newer, newer_items = generation("memo.pdf", 2, 2)
        older, older_items = generation("memo.pdf", 1, 1)
        unpromoted, unpromoted_items = generation("memo.pdf", 3, 4)
        await store.write_generation(newer, newer_items)
        await store.promote(newer)
        await store.write_generation(older, older_items)
        outcome = await store.promote(older)
        await store.write_generation(unpromoted, unpromoted_items)

        current = await read_current(store, "memo.pdf")
        history = [m.order for m in await store.history("memo.pdf")]

    assert outcome == occurrences.PromoteOutcome.SUPERSEDED
    assert current == newer_items
    assert history == [1, 2, 3]


@pytest.mark.parametrize("kind", KINDS)
async def test_concurrent_writers_get_unique_orders_and_the_highest_wins(
    kind: str,
) -> None:
    async with store_of(kind) as store:
        orders = await asyncio.gather(
            *(store.allocate_order("memo.pdf") for _ in range(10))
        )
        runs = [generation("memo.pdf", order, 1) for order in (5, 9, 7)]
        for manifest, items in runs:
            await store.write_generation(manifest, items)
        await asyncio.gather(*(store.promote(manifest) for manifest, _ in runs))

        head = await store.head("memo.pdf")

    assert sorted(orders) == list(range(1, 11))
    assert head.manifest == runs[1][0]
