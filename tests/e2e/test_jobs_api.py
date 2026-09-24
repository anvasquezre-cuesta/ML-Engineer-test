"""Asynchronous jobs over HTTP, with the worker step run in the test."""

import asyncio
import json

from fastapi import testclient
import pytest

from app.domain import errors
from app.domain import extraction
from app.ports import page_renderer
from tests.e2e import wiring
from tests.fakes import jobs as job_fakes

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.xfail(
        strict=True, raises=NotImplementedError, reason="jobs API not built"
    ),
]

PDF = b"%PDF-1.7\nminutes"
NAMES = json.dumps([{"first_name": "Anna", "last_name": "Berg"}])
UPLOAD = {"pdf_file": ("minutes.pdf", PDF, "application/pdf")}


class UnreadableRenderer(page_renderer.PageRenderer):
    """Fails the way a corrupt scan does, with a non-retryable error."""

    def render(self, pdf: bytes) -> list[extraction.PageImage]:
        """Raises the unreadable-page error.

        Args:
            pdf: Ignored.

        Raises:
            errors.OcrUnreadableError: Always.
        """
        raise errors.OcrUnreadableError()


def run_worker(client: testclient.TestClient, kit: wiring.JobKit) -> None:
    """Processes every published job message once, as the worker would.

    Args:
        client: The running app, whose process use case is used.
        kit: The job infrastructure the app was wired with.
    """
    process = client.app.state.process_job  # type: ignore[attr-defined]
    while kit.queue.published:
        message = kit.queue.published.pop(0)
        delivery = job_fakes.RecordingDelivery(message, kit.repository)
        asyncio.run(process(delivery))


def test_extract_job_returns_the_sync_result_and_records_it() -> None:
    kit = wiring.JobKit()
    with wiring.fake_client(jobs=kit, raise_server_exceptions=True) as client:
        accepted = client.post(
            "/api/jobs/extract", files=UPLOAD, data={"names": NAMES}
        )
        job_id = accepted.json()["job_id"]
        queued = client.get(f"/api/jobs/{job_id}").json()
        run_worker(client, kit)
        done = client.get(f"/api/jobs/{job_id}").json()
        sync = client.post(
            "/api/extract", files=UPLOAD, data={"names": NAMES}
        ).json()
        recorded = client.get(
            "/api/occurrences", params={"document_key": "minutes.pdf"}
        ).json()

    assert accepted.status_code == 202
    assert queued["status"] == "queued"
    assert (done["status"], done["attempts"]) == ("succeeded", 1)
    assert done["extraction"] == sync
    assert [o["name"] for o in recorded] == [
        n["name"] for n in sync["extracted_names"]
    ]


def test_unreadable_document_is_listed_as_dead_lettered() -> None:
    kit = wiring.JobKit()
    with wiring.fake_client(
        renderer=UnreadableRenderer(), jobs=kit, raise_server_exceptions=True
    ) as client:
        job_id = client.post(
            "/api/jobs/extract", files=UPLOAD, data={"names": NAMES}
        ).json()["job_id"]
        run_worker(client, kit)
        dead = client.get(
            "/api/jobs", params={"status": "dead_lettered"}
        ).json()

    assert [
        (j["job_id"], j["dead_lettered"], j["last_error_code"]) for j in dead
    ] == [(job_id, True, "ocr.unreadable")]
