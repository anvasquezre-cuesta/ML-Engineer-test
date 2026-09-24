"""Worker process entrypoint: ``python -m app.worker_main``.

It builds the use cases once and runs queued jobs until SIGINT or SIGTERM;
a job interrupted mid-run is redelivered by the broker, or recovered by the
reaper once its lease lapses.
"""

import asyncio
import signal

import structlog

from app import bootstrap
from app import config
from app import logging_config
from app.worker import loop

log = structlog.stdlib.get_logger(__name__)


async def run(settings: config.Settings) -> None:
    """Builds the use cases once and works until a stop signal.

    Args:
        settings: The service configuration.
    """
    container = bootstrap.build_container(settings)
    for step in container.startup:
        await step()
    stop = asyncio.Event()
    running = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        running.add_signal_handler(stop_signal, stop.set)
    log.info("worker.started")
    await loop.serve(
        container.job_queue,
        container.process_job,
        container.reap_jobs,
        settings.jobs.reap_interval_s,
        stop,
    )
    log.info("worker.stopped")


def main() -> None:
    """Starts the worker with settings from the environment."""
    settings = config.Settings()
    logging_config.configure_logging(settings.logging)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
