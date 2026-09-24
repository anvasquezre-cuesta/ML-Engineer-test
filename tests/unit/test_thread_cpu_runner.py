"""Tests for the thread-backed CpuRunner used for OCR, NER and rendering."""

import asyncio
from collections.abc import Iterator
import threading
import time

import pytest
import structlog

from app.adapters.cpu_runner.thread_runner import ThreadCpuRunner


@pytest.fixture(autouse=True)
def clean_log_context() -> Iterator[None]:
    """Clears the structlog context before and after each test.

    Yields:
        Nothing; the test runs between the two clears.
    """
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _read_request_id(delay_s: float) -> object:
    """Waits, then returns the request_id bound in the log context.

    Args:
        delay_s: Seconds to block before reading.

    Returns:
        The bound ``request_id``, or ``None``.
    """
    time.sleep(delay_s)
    return structlog.contextvars.get_contextvars().get("request_id")


async def test_concurrent_calls_keep_their_own_log_context() -> None:
    runner = ThreadCpuRunner(max_concurrency=5)

    async def call(request_id: str) -> object:
        structlog.contextvars.bind_contextvars(request_id=request_id)
        return await runner.run(_read_request_id, 0.01)

    ids = [f"req-{index}" for index in range(5)]
    results = await asyncio.gather(*(call(request_id) for request_id in ids))
    assert list(results) == ids


async def test_thread_runner_runs_in_parallel_up_to_the_cap() -> None:
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def work() -> None:
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.05)
        with lock:
            state["running"] -= 1

    runner = ThreadCpuRunner(max_concurrency=2)
    await asyncio.gather(*(runner.run(work) for _ in range(6)))
    assert state["peak"] == 2
