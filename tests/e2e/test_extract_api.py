"""``POST /api/extract`` over HTTP: real pipeline and failure contract."""

import dataclasses
import json
from typing import Any

from fastapi import testclient
import pytest

from app import bootstrap
from app import config
from app import main
from app.domain import extraction
from app.ports import page_renderer
from app.service_layer import occurrences as occurrence_service
from tests import ground_truth
from tests.e2e import wiring
from tests.fakes import occurrence_store

pytestmark = pytest.mark.e2e

PDF = b"%PDF-1.7\n"
NAMES = json.dumps([{"first_name": "Anna", "last_name": "Berg"}])
PROBLEM_JSON = "application/problem+json"


class ExplodingRenderer(page_renderer.PageRenderer):
    """Fails the way an unforeseen bug would."""

    def render(self, pdf: bytes) -> list[extraction.PageImage]:
        """Raises an error carrying internal details.

        Args:
            pdf: Ignored.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError("secret internal detail /srv/tmp/upload-42")


def post_extract(
    client: testclient.TestClient, content: bytes, names: str = NAMES
) -> dict[str, Any]:
    """Posts a PDF upload and returns the JSON body.

    Args:
        client: The test client.
        content: The uploaded file content.
        names: The ``names`` form field.

    Returns:
        The decoded response body, with ``status`` and ``content_type`` of
        the HTTP response added.
    """
    response = client.post(
        "/api/extract",
        files={"pdf_file": ("scan.pdf", content, "application/pdf")},
        data={"names": names},
    )
    return {
        **response.json(),
        "http_status": response.status_code,
        "content_type": response.headers["content-type"],
        "request_id_header": response.headers.get("x-request-id"),
    }


def in_memory_records(settings: config.Settings) -> bootstrap.Container:
    """Builds the real container with occurrences recorded in memory.

    Args:
        settings: The service configuration.

    Returns:
        The container, needing no DynamoDB.
    """
    container = bootstrap.build_container(settings)
    recorded = occurrence_store.InMemoryOccurrenceStore()
    return dataclasses.replace(
        container,
        record_extraction=occurrence_service.ExtractAndRecord(
            container.extract_names,
            recorded,
            occurrence_service.RecordOccurrences(recorded, "real-models"),
        ),
        query_occurrences=occurrence_service.QueryOccurrences(recorded),
        startup=(),
    )


@pytest.mark.integration
def test_sample_pdf_returns_every_verified_box_and_fuzzy_match() -> None:
    truth = json.loads(
        (ground_truth.GROUND_TRUTH / "company_memo.json").read_text()
    )
    queries = [
        {"first_name": "Maria", "last_name": "Garcia"},
        {"first_name": "Margaret", "last_name": "Thomson"},
    ]

    with testclient.TestClient(
        main.create_app(config.Settings(_env_file=None), in_memory_records)
    ) as client:
        response = client.post(
            "/api/extract",
            files={
                "pdf_file": (
                    "company_memo.pdf",
                    (ground_truth.SAMPLES / "company_memo.pdf").read_bytes(),
                    "application/pdf",
                )
            },
            data={"names": json.dumps(queries)},
        )

    body = response.json()
    found = tuple(
        extraction.NameOccurrence(
            name=item["name"],
            page_number=item["bounding_box"]["page_number"],
            box=extraction.Box(
                x=item["bounding_box"]["x"],
                y=item["bounding_box"]["y"],
                width=item["bounding_box"]["width"],
                height=item["bounding_box"]["height"],
            ),
        )
        for item in body["extracted_names"]
    )
    assert response.status_code == 200
    assert ground_truth.unmatched(found, truth["names"]) == ([], [])
    matches = {
        (match["extracted_name"], match["matched_name"]): match["score"]
        for match in body["fuzzy_matches"]
    }
    assert matches[("Maria Garcia", "Maria Garcia")] == 1.0
    assert 0.9 <= matches[("Margaret Thompson", "Margaret Thomson")] < 1.0


@pytest.mark.parametrize(
    ("content", "names", "status", "code"),
    [
        (b"\x89PNG\r\n\x1a\n", NAMES, 415, "upload.not_pdf"),
        (PDF + b"x" * wiring.UPLOAD_LIMIT, NAMES, 413, "upload.too_large"),
        (
            PDF,
            json.dumps([{"first_name": "Anna"}]),
            422,
            "request.invalid_names_json",
        ),
    ],
    ids=["png", "too-large", "names-missing-last"],
)
def test_invalid_requests_are_rejected_as_problem_details(
    content: bytes, names: str, status: int, code: str
) -> None:
    with wiring.fake_client() as client:
        body = post_extract(client, content, names)

    assert (body["http_status"], body["code"]) == (status, code)
    assert body["content_type"] == PROBLEM_JSON


def test_unexpected_failure_hides_internals_and_returns_request_id() -> None:
    with wiring.fake_client(ExplodingRenderer()) as client:
        body = post_extract(client, PDF)

    assert (body["http_status"], body["code"]) == (500, "internal.unexpected")
    assert "secret" not in json.dumps(body)
    assert body["request_id"] == body["request_id_header"]


def test_logs_never_contain_extracted_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with wiring.fake_client() as client:
        body = post_extract(client, PDF)

    logs = capsys.readouterr()
    assert body["http_status"] == 200
    assert body["request_id_header"] in logs.out
    assert "Anna Berg" not in logs.out + logs.err
    assert "Lucas Moreau" not in logs.out + logs.err
