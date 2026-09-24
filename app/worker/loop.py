"""Worker loops: run delivered jobs, and reap stuck ones on a schedule."""

import asyncio

import structlog

from app.ports import job_queue
from app.service_layer import jobs

log = structlog.stdlib.get_logger(__name__)


async def consume(queue: job_queue.JobQueue, process: jobs.ProcessJob) -> None:
    """Processes deliveries one after another, forever.

    Args:
        queue: Delivers the jobs.
        process: Runs one delivered job and settles it.
    """
    async for delivery in queue.consume():
        await process(delivery)


async def reap(reaper: jobs.ReapJobs, interval_s: float) -> None:
    """Runs a reaper pass every ``interval_s`` seconds, forever.

    A failed pass is logged and the next one runs on schedule.

    Args:
        reaper: Recovers jobs of dead workers and lost messages.
        interval_s: Seconds between passes.
    """
    while True:
        try:
            await reaper()
        except Exception:
            log.exception("worker.reap_failed")
        await asyncio.sleep(interval_s)


async def serve(
    queue: job_queue.JobQueue,
    process: jobs.ProcessJob,
    reaper: jobs.ReapJobs,
    interval_s: float,
    stop: asyncio.Event,
) -> None:
    """Runs the consumer and the reaper until ``stop`` is set.

    If either loop fails on its own, its error ends the worker so the
    orchestrator restarts it.

    Args:
        queue: Delivers the jobs.
        process: Runs one delivered job.
        reaper: Recovers stuck jobs.
        interval_s: Seconds between reaper passes.
        stop: Set to stop the worker.
    """
    tasks = [
        asyncio.create_task(consume(queue, process)),
        asyncio.create_task(reap(reaper, interval_s)),
    ]
    stopped = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait(
        [stopped, *tasks], return_when=asyncio.FIRST_COMPLETED
    )
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for task in tasks:
        if task in done:
            task.result()
