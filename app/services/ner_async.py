"""Bounded, persistent and supervised NER workers for asynchronous callers."""

import asyncio
import json
import os
import signal
import sys

import anyio

from app.core.config import Settings, get_settings
from app.core.worker_environment import worker_environment
from app.models.extraction import PersonSpan
from app.services.ner_protocol import MAX_NER_RESPONSE_BYTES
from app.services.ner_service import (
    NERBusyError,
    NERInputError,
    NERModelUnavailableError,
    NERProcessingError,
    NERTimeoutError,
    validate_pages,
)


async def _terminate_worker(process: asyncio.subprocess.Process) -> None:
    """Terminate the worker's POSIX process group and reap the process."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=1.0)
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def _start_worker() -> asyncio.subprocess.Process:
    """If startup is cancelled, obtain the process handle and terminate it."""
    if os.name != "posix":
        raise NERProcessingError("Supervised NER workers require a POSIX platform")
    task = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.ner_worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        limit=MAX_NER_RESPONSE_BYTES, env=worker_environment(),
    ))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            process = await task
        except Exception:
            raise asyncio.CancelledError from None
        await _terminate_worker(process)
        raise
    except OSError:
        raise NERProcessingError("Could not start NER worker") from None


async def _send(process: asyncio.subprocess.Process, message: dict) -> None:
    assert process.stdin is not None
    try:
        data = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"
        process.stdin.write(data)
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError, OSError):
        raise NERProcessingError("NER worker communication failed") from None


async def _receive(process: asyncio.subprocess.Process) -> dict:
    assert process.stdout is not None
    try:
        line = await process.stdout.readline()
        if not line or len(line) > MAX_NER_RESPONSE_BYTES:
            raise ValueError("Invalid worker response")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise ValueError("Invalid worker response")
        return message
    except (OSError, ValueError, RecursionError):
        raise NERProcessingError("NER worker returned an invalid response") from None


def _parse_result(message: dict, pages: tuple[str, ...]) -> list[list[PersonSpan]]:
    status = message.get("status")
    if status == "model_unavailable":
        raise NERModelUnavailableError("The configured NER model is unavailable")
    if status == "input_error":
        raise NERInputError("NER input is invalid or exceeds its limit")
    if status != "ok":
        raise NERProcessingError("NER worker failed to process the document")
    try:
        result = message["pages"]
        if not isinstance(result, list) or len(result) != len(pages):
            raise ValueError("Invalid page count")
        parsed = []
        for text, entities in zip(pages, result):
            if not isinstance(entities, list):
                raise ValueError("Invalid page result")
            spans = [PersonSpan(**entity) for entity in entities]
            if any(span.char_end > len(text) or text[span.char_start:span.char_end] != span.text for span in spans):
                raise ValueError("Invalid page-local span")
            parsed.append(spans)
        return parsed
    except (KeyError, TypeError, ValueError):
        raise NERProcessingError("NER worker returned an invalid result") from None


class _WorkerSlot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None

    async def detect(self, pages: tuple[str, ...]) -> list[list[PersonSpan]]:
        if self.process is None:
            self.process = await _start_worker()
            await _send(self.process, {
                "model": self.settings.ner_model,
                "max_page_chars": self.settings.ner_max_page_chars,
                "max_document_chars": self.settings.ner_max_document_chars,
                "max_pages": self.settings.max_pdf_pages,
            })
            ready = await _receive(self.process)
            if ready.get("status") == "model_unavailable":
                raise NERModelUnavailableError("The configured NER model is unavailable")
            if ready.get("status") != "ready":
                raise NERProcessingError("NER worker could not initialize")
        await _send(self.process, {"pages": pages})
        return _parse_result(await _receive(self.process), pages)

    async def reset(self) -> None:
        process, self.process = self.process, None
        if process is not None:
            # Cleanup must continue even if a caller cancels this supervisor.
            task = asyncio.create_task(_terminate_worker(process))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise

    async def close(self) -> None:
        if self.process is None:
            return
        process = self.process
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=self.settings.ner_shutdown_timeout_seconds)
        except TimeoutError:
            await self.reset()
        else:
            # Reap any unexpected children in the worker's process group too.
            await self.reset()


class NERService:
    """One service per application process, with bounded jobs and worker reuse."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings if settings is not None else get_settings()
        self._process_limiter = anyio.Semaphore(self.settings.ner_max_concurrent_jobs)
        self._admission = anyio.Semaphore(
            self.settings.ner_max_concurrent_jobs + self.settings.ner_max_queued_jobs
        )
        self._slots = [_WorkerSlot(self.settings) for _ in range(self.settings.ner_max_concurrent_jobs)]
        self._available: asyncio.Queue[_WorkerSlot] = asyncio.Queue()
        for slot in self._slots:
            self._available.put_nowait(slot)
        self._tasks: set[asyncio.Task] = set()
        self._started: set[asyncio.Task] = set()
        self._closing = False
        self._shutdown_task: asyncio.Task | None = None

    async def detect_pages(self, pages: list[str] | tuple[str, ...]) -> list[list[PersonSpan]]:
        """Detect each page independently without running spaCy on the event loop."""
        source = validate_pages(
            pages, max_pages=self.settings.max_pdf_pages,
            max_page_chars=self.settings.ner_max_page_chars,
            max_document_chars=self.settings.ner_max_document_chars,
        )
        if self._closing:
            raise NERBusyError("NER service is shutting down")
        try:
            self._admission.acquire_nowait()
        except anyio.WouldBlock:
            raise NERBusyError("NER capacity is full") from None

        try:
            task = asyncio.create_task(self._run_admitted(source))
        except BaseException:
            self._admission.release()
            raise
        self._tasks.add(task)

        def finished(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            self._started.discard(done)
            self._admission.release()
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task not in self._started:
                task.cancel()
            raise

    async def _run_admitted(self, pages: tuple[str, ...]) -> list[list[PersonSpan]]:
        try:
            with anyio.fail_after(self.settings.ner_queue_timeout_seconds):
                await self._process_limiter.acquire()
        except TimeoutError:
            raise NERBusyError("NER queue wait timed out") from None
        try:
            task = asyncio.current_task()
            assert task is not None
            self._started.add(task)
            try:
                async with asyncio.timeout(self.settings.ner_job_timeout_seconds):
                    return await self._execute_job(pages)
            except TimeoutError:
                raise NERTimeoutError("NER job deadline exceeded") from None
        finally:
            self._process_limiter.release()

    async def _execute_job(self, pages: tuple[str, ...]) -> list[list[PersonSpan]]:
        slot = await self._available.get()
        try:
            return await slot.detect(pages)
        except BaseException:
            await slot.reset()
            raise
        finally:
            self._available.put_nowait(slot)

    async def _shutdown(self) -> None:
        tasks = set(self._tasks)
        for task in tasks - self._started:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.settings.ner_shutdown_timeout_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for slot in self._slots:
            await slot.close()

    async def aclose(self) -> None:
        """Stop admission, finish or terminate jobs, and close persistent workers."""
        self._closing = True
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._shutdown())
        await asyncio.shield(self._shutdown_task)
