"""Querying occurrences: filters and the completeness of each version."""

import pytest

from app.domain import errors
from app.domain import extraction
from app.service_layer import occurrences as occurrence_service
from tests.fakes import occurrence_store


async def stored(
    documents: dict[str, list[str]],
) -> occurrence_store.InMemoryOccurrenceStore:
    """Records one version of each document with the given names.

    Args:
        documents: Names per document key.

    Returns:
        The store.
    """
    store = occurrence_store.InMemoryOccurrenceStore()
    recorder = occurrence_service.RecordOccurrences(store, "extractor")
    for key, names in documents.items():
        found = [
            extraction.NameOccurrence(name, 0, extraction.Box(0, 0, 1, 1))
            for name in names
        ]
        order = await store.allocate_order(key)
        await recorder(key, f"hash-{key}", order, found, "sync")
    return store


async def test_name_filter_ignores_case_and_accents_across_documents() -> None:
    store = await stored(
        {"memo.pdf": ["José Pérez", "Anna Berg"], "minutes.pdf": ["JOSE PEREZ"]}
    )
    query = occurrence_service.QueryOccurrences(store)

    everywhere = [o async for o in query(name="jose perez")]
    in_minutes = [o async for o in query("minutes.pdf", name="Pérez")]

    assert sorted((o.document_key, o.name) for o in everywhere) == [
        ("memo.pdf", "José Pérez"),
        ("minutes.pdf", "JOSE PEREZ"),
    ]
    assert [(o.document_key, o.name) for o in in_minutes] == [
        ("minutes.pdf", "JOSE PEREZ")
    ]


async def test_version_missing_occurrences_is_never_returned_partly() -> None:
    store = await stored({"memo.pdf": ["Anna Berg", "Lucas Moreau"]})
    store.lose_on_read = 1
    query = occurrence_service.QueryOccurrences(store)

    with pytest.raises(errors.OccurrenceIntegrityError):
        [o async for o in query()]


@pytest.mark.xfail(strict=True, raises=NotImplementedError)
async def test_export_holding_exactly_the_limit_is_returned_whole() -> None:
    store = await stored(
        {"memo.pdf": ["Anna Berg"], "minutes.pdf": ["Omar Haddad"]}
    )
    query = occurrence_service.QueryOccurrences(store)
    export = occurrence_service.ExportOccurrences(query, max_rows=2)

    rows = await export()

    assert sorted(o.name for o in rows) == ["Anna Berg", "Omar Haddad"]


@pytest.mark.xfail(strict=True, raises=NotImplementedError)
async def test_export_past_the_limit_is_refused_without_reading_on() -> None:
    store = await stored(
        {"a.pdf": ["Anna Berg"], "b.pdf": ["Omar Haddad"], "c.pdf": ["Li Wei"]}
    )
    store.fail_reads_after = 2
    query = occurrence_service.QueryOccurrences(store)
    export = occurrence_service.ExportOccurrences(query, max_rows=1)

    with pytest.raises(errors.OccurrenceExportTooLargeError):
        await export()
