"""Job processing: retries, dead letters, idempotency and races."""

import asyncio
from collections.abc import Sequence
import dataclasses
import datetime

from app.domain import errors
from app.domain import extraction
from app.domain import jobs
from app.domain import rag
from app.service_layer import jobs as job_service
from app.service_layer import occurrences
from tests.fakes import jobs as job_fakes
from tests.fakes import occurrence_store

NOW = datetime.datetime(2026, 9, 24, 12, tzinfo=datetime.UTC)
EXTRACT = jobs.JobKind.EXTRACT


@dataclasses.dataclass
class Worker:
    """The use cases over in-memory stores, with a scripted extractor.

    Attributes:
        repository: The job store.
        queue: Records published messages.
        recorded: The occurrence store.
        submit: Submits jobs.
        process: Processes deliveries.
        runs: PDFs the extractor was called with.
        failures: Errors the next extractions raise, in order.
    """

    repository: job_fakes.InMemoryJobRepository
    queue: job_fakes.RecordingJobQueue
    recorded: occurrence_store.InMemoryOccurrenceStore
    submit: job_service.SubmitJob
    process: job_service.ProcessJob
    runs: list[bytes]
    failures: list[Exception]

    def delivery(self, index: int = 0) -> job_fakes.RecordingDelivery:
        """Delivers a published message again.

        Args:
            index: Which published message.

        Returns:
            A fresh delivery of it.
        """
        return job_fakes.RecordingDelivery(
            self.queue.published[index], self.repository
        )


def worker(failures: Sequence[Exception] = ()) -> Worker:
    """Builds the job use cases over fakes.

    The extractor names the PDF's last line, and yields to the event loop
    so concurrent deliveries interleave.

    Args:
        failures: Errors the first extractions raise.

    Returns:
        The worker.
    """
    repository = job_fakes.InMemoryJobRepository()
    blobs = job_fakes.InMemoryBlobStore()
    queue = job_fakes.RecordingJobQueue()
    recorded = occurrence_store.InMemoryOccurrenceStore()
    runs: list[bytes] = []
    pending = list(failures)

    async def extract(
        pdf: bytes, names: Sequence[extraction.QueryName]
    ) -> extraction.ExtractionResult:
        runs.append(pdf)
        await asyncio.sleep(0)
        if pending:
            raise pending.pop(0)
        name = pdf.decode().splitlines()[-1]
        box = extraction.Box(10.0, 20.0, 30.0, 8.0)
        return extraction.ExtractionResult(
            (extraction.NameOccurrence(name, 0, box),), ()
        )

    async def ingest(pdf: bytes, document_key: str) -> rag.IngestResult:
        return rag.IngestResult(document_key, rag.IngestStatus.INGESTED, 1)

    return Worker(
        repository,
        queue,
        recorded,
        job_service.SubmitJob(
            blobs, repository, queue, recorded, 3, lambda: NOW
        ),
        job_service.ProcessJob(
            repository,
            blobs,
            extract,
            occurrences.RecordOccurrences(recorded, "extractor"),
            ingest,
            lambda: NOW,
            lease_s=60,
            retry_delay_s=10,
        ),
        runs,
        pending,
    )


async def test_retryable_failures_back_off_then_dead_letter() -> None:
    w = worker([errors.OcrEngineError()] * 3)
    job = await w.submit(EXTRACT, b"%PDF\nAnna Berg", None, "memo.pdf")

    settled = []
    for _ in range(3):
        delivery = w.delivery()
        await w.process(delivery)
        settled.append(delivery.settled)

    stored = w.repository.jobs[job.job_id]
    assert settled == [
        ["retry:10"],
        ["retry:20"],
        ["dead_letter:dead_lettered"],
    ]
    assert (stored.status, stored.attempts, stored.last_error_code) == (
        jobs.JobStatus.DEAD_LETTERED,
        3,
        "ocr.engine_failure",
    )


async def test_poison_failure_is_dead_lettered_in_the_store_first() -> None:
    w = worker([errors.OcrUnreadableError()])
    await w.submit(EXTRACT, b"%PDF\nAnna Berg", None, "memo.pdf")
    delivery = w.delivery()

    await w.process(delivery)

    assert delivery.settled == ["dead_letter:dead_lettered"]


async def test_redelivered_finished_job_is_acked_without_running() -> None:
    w = worker()
    job = await w.submit(EXTRACT, b"%PDF\nAnna Berg", None, "memo.pdf")
    first, again = w.delivery(), w.delivery()

    await w.process(first)
    await w.process(again)

    assert (first.settled, again.settled) == (["ack"], ["ack"])
    assert len(w.runs) == 1
    assert w.repository.jobs[job.job_id].status is jobs.JobStatus.SUCCEEDED


async def test_concurrent_deliveries_run_a_job_once() -> None:
    w = worker()
    await w.submit(EXTRACT, b"%PDF\nAnna Berg", None, "memo.pdf")
    first, second = w.delivery(), w.delivery()

    await asyncio.gather(w.process(first), w.process(second))

    assert len(w.runs) == 1
    assert (first.settled, second.settled) == (["ack"], ["ack"])


async def test_late_older_extract_job_cannot_replace_a_newer_version() -> None:
    w = worker()
    await w.submit(EXTRACT, b"%PDF\nAnna Berg", "memo", None)
    await w.submit(EXTRACT, b"%PDF\nLucas Moreau", "memo", None)

    await w.process(w.delivery(1))
    await w.process(w.delivery(0))

    head = await w.recorded.head("memo")
    current = [o.name async for o in w.recorded.current(head)]
    assert current == ["Lucas Moreau"]
    assert {j.status for j in w.repository.jobs.values()} == {
        jobs.JobStatus.SUCCEEDED
    }
