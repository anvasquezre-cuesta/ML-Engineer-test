"""Occurrence records: one consistent current version per document."""

import pytest

from app.domain import errors
from app.domain import extraction
from app.domain import occurrences
from app.service_layer import occurrences as occurrence_service
from tests.fakes import occurrence_store

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="occurrence store not built"
)

EXTRACTOR = "ner=en_core_web_lg|ocr=eng@300dpi"
Store = occurrence_store.InMemoryOccurrenceStore


def found(*names: str) -> list[extraction.NameOccurrence]:
    """Builds one occurrence per name, each on its own page and line.

    Args:
        *names: The names, in document order.

    Returns:
        The occurrences.
    """
    return [
        extraction.NameOccurrence(
            name, index % 2, extraction.Box(72.0, 20.0 * index, 90.5, 9.1)
        )
        for index, name in enumerate(names)
    ]


async def record(
    store: Store,
    key: str,
    content_hash: str,
    names: list[str],
    order: int | None = None,
    extractor: str = EXTRACTOR,
) -> occurrences.RecordOutcome:
    """Records ``names`` as one extraction run of a document version.

    Args:
        store: The store.
        key: The document key.
        content_hash: The version.
        names: The names the run found.
        order: Acceptance order; a new one is allocated when omitted.
        extractor: Fingerprint of the run's models.

    Returns:
        The outcome.
    """
    if order is None:
        order = await store.allocate_order(key)
    recorder = occurrence_service.RecordOccurrences(store, extractor)
    return await recorder(key, content_hash, order, found(*names), "sync")


async def listed(store: Store) -> list[occurrences.StoredOccurrence]:
    """Collects the current occurrences of every document.

    Args:
        store: The store.

    Returns:
        The occurrences.
    """
    return [
        occurrence
        async for head in store.documents()
        async for occurrence in store.current(head)
    ]


async def test_rerun_finding_fewer_names_replaces_the_whole_version() -> None:
    store = Store()
    twelve = [f"Person {n}" for n in range(12)]
    await record(store, "memo.pdf", "h1", twelve)

    outcome = await record(
        store, "memo.pdf", "h1", twelve[:11], extractor="ner=en_core_web_trf"
    )

    rows = await listed(store)
    assert outcome == occurrences.RecordOutcome.RECORDED
    assert [(r.name, r.page_number, r.box) for r in rows] == [
        (o.name, o.page_number, o.box) for o in found(*twelve[:11])
    ]
    assert len(await store.history("memo.pdf")) == 2


async def test_same_content_and_extractor_is_recorded_once() -> None:
    store = Store()
    await record(store, "memo.pdf", "h1", ["Anna Berg"])

    outcome = await record(store, "memo.pdf", "h1", ["Anna Berg"])

    assert outcome == occurrences.RecordOutcome.UNCHANGED
    assert [r.name for r in await listed(store)] == ["Anna Berg"]
    assert len(await store.history("memo.pdf")) == 1


async def test_late_older_request_cannot_roll_a_document_back() -> None:
    store = Store()
    older = await store.allocate_order("memo.pdf")
    newer = await store.allocate_order("memo.pdf")
    await record(store, "memo.pdf", "new", ["Lucas Moreau"], order=newer)

    outcome = await record(store, "memo.pdf", "old", ["Anna Berg"], order=older)

    assert outcome == occurrences.RecordOutcome.SUPERSEDED
    assert [r.name for r in await listed(store)] == ["Lucas Moreau"]
    assert len(await store.history("memo.pdf")) == 2


async def test_failed_write_keeps_the_previous_version_visible() -> None:
    store = Store()
    await record(store, "memo.pdf", "h1", ["Anna Berg"])
    store.fail_after = 1

    with pytest.raises(errors.OccurrenceStoreUnavailableError):
        await record(store, "memo.pdf", "h2", ["Lucas Moreau", "Yuki Tanaka"])
    before_retry = [r.name for r in await listed(store)]
    await record(store, "memo.pdf", "h2", ["Lucas Moreau", "Yuki Tanaka"])

    assert before_retry == ["Anna Berg"]
    assert [r.name for r in await listed(store)] == [
        "Lucas Moreau",
        "Yuki Tanaka",
    ]
