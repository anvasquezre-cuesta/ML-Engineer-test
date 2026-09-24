"""Recorded occurrences over HTTP: what extract returns is what is stored."""

import csv
import io
import json

from fastapi import testclient
import httpx2
import pytest

from tests.e2e import wiring
from tests.fakes import occurrence_store

pytestmark = pytest.mark.e2e

PDF = b"%PDF-1.7\nminutes"
NAMES = json.dumps([{"first_name": "Anna", "last_name": "Berg"}])


def extract(
    client: testclient.TestClient, document_key: str | None = None
) -> httpx2.Response:
    """Posts ``PDF`` as ``minutes.pdf`` to the extract endpoint.

    Args:
        client: The test client.
        document_key: The optional ``document_key`` form field.

    Returns:
        The response.
    """
    form = {"names": NAMES}
    if document_key is not None:
        form["document_key"] = document_key
    return client.post(
        "/api/extract",
        files={"pdf_file": ("minutes.pdf", PDF, "application/pdf")},
        data=form,
    )


def test_extracted_names_are_stored_listed_and_exported_as_returned() -> None:
    with wiring.fake_client(raise_server_exceptions=True) as client:
        returned = extract(client).json()["extracted_names"]
        extract(client, document_key="board-2024")
        listed = client.get("/api/occurrences").json()
        anna_in_board = client.get(
            "/api/occurrences",
            params={"document_key": "board-2024", "name": "ANNA berg"},
        ).json()
        exported = client.get(
            "/api/occurrences/export", params={"format": "csv"}
        ).text

    as_returned = sorted(
        (n["name"], json.dumps(n["bounding_box"], sort_keys=True))
        for n in returned
    )
    for key in ("minutes.pdf", "board-2024"):
        assert as_returned == sorted(
            (o["name"], json.dumps(o["bounding_box"], sort_keys=True))
            for o in listed
            if o["document_key"] == key
        )
    assert len({o["occurrence_id"] for o in listed}) == len(listed) == 4
    assert [(o["document_key"], o["name"]) for o in anna_in_board] == [
        ("board-2024", "Anna Berg")
    ]
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert sorted(r["occurrence_id"] for r in rows) == sorted(
        o["occurrence_id"] for o in listed
    )


def test_store_outage_fails_extract_without_returning_names() -> None:
    recorded = occurrence_store.InMemoryOccurrenceStore()
    recorded.fail_after = 0

    with wiring.fake_client(recorded=recorded) as client:
        response = extract(client)

    assert (response.status_code, response.json()["code"]) == (
        503,
        "occurrence_store.unavailable",
    )
    assert "Anna" not in response.text


@pytest.mark.xfail(strict=True, raises=AssertionError)
@pytest.mark.parametrize("export_format", ["json", "csv"])
def test_export_that_cannot_be_read_fails_instead_of_looking_empty(
    export_format: str,
) -> None:
    recorded = occurrence_store.InMemoryOccurrenceStore()
    with wiring.fake_client(recorded=recorded) as client:
        extract(client)
        recorded.lose_on_read = 1
        response = client.get(
            "/api/occurrences/export", params={"format": export_format}
        )

    assert response.status_code == 500
    assert response.json()["code"] == "occurrence_store.integrity"
