"""Real spaCy/model and supervised NER worker checks; not the extraction endpoint."""

import asyncio
from importlib.metadata import version
import os
from pathlib import Path
import sys

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import app as actual_app
from app.services.ner_async import NERService
from app.services.ner_protocol import MAX_NER_RESPONSE_BYTES
from app.services.ner_service import NERBusyError, NERModelUnavailableError, NERProcessingError, NERTimeoutError, SpacyPersonRecognizer
from app.services.ocr_service import OCRService


@pytest.fixture(scope="module")
def recognizer():
    return SpacyPersonRecognizer.load("en_core_web_sm", 100_000)


def test_packaged_model_and_spacy_versions_are_compatible(recognizer):
    assert version("en-core-web-sm") == "3.8.0"
    assert version("spacy").startswith("3.8.")
    assert "ner" in recognizer._nlp.pipe_names


def test_real_model_detects_persons_and_spans_on_separate_pages(recognizer):
    pages = (
        "Barack Obama met Angela Merkel in Berlin on Monday.",
        "Alice Johnson met Alice Johnson at Google in London.",
        "",
    )
    results = recognizer.detect_pages(pages)
    assert [[span.text for span in result] for result in results] == [
        ["Barack Obama", "Angela Merkel"], ["Alice Johnson", "Alice Johnson"], [],
    ]
    for text, spans in zip(pages, results):
        assert all(text[span.char_start:span.char_end] == span.text for span in spans)
    assert results[1][0].char_start != results[1][1].char_start


def test_real_worker_reuses_process_and_shuts_down_cleanly():
    pages = ["Barack Obama met Angela Merkel in Berlin.", "Alice Johnson met Alice Johnson."]

    async def run():
        service = NERService(Settings(ner_max_concurrent_jobs=1))
        process = None
        try:
            first = await service.detect_pages(pages)
            process = service._slots[0].process
            assert process is not None and process.returncode is None
            second = await service.detect_pages(pages)
            assert service._slots[0].process is process
            assert first == second
            assert [[span.text for span in result] for result in first] == [
                ["Barack Obama", "Angela Merkel"], ["Alice Johnson", "Alice Johnson"],
            ]
            assert all(
                page[span.char_start:span.char_end] == span.text
                for page, result in zip(pages, first) for span in result
            )
        finally:
            await service.aclose()
        assert process.returncode is not None

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_health_remains_responsive_during_real_model_inference():
    page = "Alice Johnson met Bob Smith at Google. " * 500
    service = NERService(Settings(ner_job_timeout_seconds=30))

    async def run():
        try:
            # Warm the persistent process before checking inference itself.
            await service.detect_pages(["Alice Johnson met Bob Smith."])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=actual_app), base_url="http://test") as client:
                request = asyncio.create_task(service.detect_pages([page]))
                await asyncio.sleep(0.02)
                assert not request.done()
                health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
                assert health.status_code == 200
                result = await request
                assert result and result[0]
        finally:
            await service.aclose()

    asyncio.run(run())


def test_missing_model_fails_in_worker_without_silent_empty_result():
    async def run():
        service = NERService(Settings(ner_model="model_that_does_not_exist"))
        try:
            with pytest.raises(NERModelUnavailableError) as caught:
                await service.detect_pages(["Jane Doe"])
            assert "Jane Doe" not in str(caught.value)
            assert service._slots[0].process is None
        finally:
            await service.aclose()

    asyncio.run(run())


def test_real_ocr_then_ner_on_multiple_pages(recognizer):
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))
    document = OCRService().extract_file(sample_dir / "meeting_minutes.pdf")
    pages = tuple(page.text for page in document.pages)
    results = recognizer.detect_pages(pages)
    assert len(results) == 2
    assert {"Richard Hernandez", "Thomas Muller"} <= {span.text for span in results[0]}
    assert {"Thomas Muller", "Catherine Dubois"} <= {span.text for span in results[1]}
    assert all(
        page[span.char_start:span.char_end] == span.text
        for page, result in zip(pages, results) for span in result
    )
    # This is only a smoke test for known names, not an accuracy assessment.


def fake_worker_script(*, delay, ignore_sigterm=False, marker=None):
    return f"""
import json, signal, sys, time
from pathlib import Path
if {ignore_sigterm!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
config = json.loads(sys.stdin.readline())
print(json.dumps({{"status": "ready"}}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if {str(marker) if marker else None!r} is not None:
        Path({str(marker) if marker else None!r}).write_text("started")
    time.sleep({delay!r})
    print(json.dumps({{"status": "ok", "pages": [[] for _ in request["pages"]]}}), flush=True)
"""


def install_fake_start(monkeypatch, scripts):
    processes = []

    async def start():
        script = scripts[min(len(processes), len(scripts) - 1)]
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "-c", script, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=MAX_NER_RESPONSE_BYTES,
        )
        processes.append(process)
        return process

    monkeypatch.setattr("app.services.ner_async._start_worker", start)
    return processes


async def wait_for_marker(marker):
    async with asyncio.timeout(5):
        while not marker.exists():
            await asyncio.sleep(0.01)


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_timeout_terminates_unresponsive_worker_and_replaces_it(monkeypatch, tmp_path):
    marker = tmp_path / "started"
    processes = install_fake_start(monkeypatch, [
        fake_worker_script(delay=30, ignore_sigterm=True, marker=marker),
        fake_worker_script(delay=0),
    ])

    async def run():
        service = NERService(Settings(ner_job_timeout_seconds=1.0))
        try:
            first = asyncio.create_task(service.detect_pages(["name"]))
            await wait_for_marker(marker)
            with pytest.raises(NERTimeoutError):
                await first
            assert processes[0].returncode is not None
            assert await service.detect_pages(["next"]) == [[]]
            assert len(processes) == 2 and processes[1].pid != processes[0].pid
        finally:
            await service.aclose()
        assert all(process.returncode is not None for process in processes)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_started_cancellation_keeps_worker_busy_until_it_really_finishes(monkeypatch, tmp_path):
    marker = tmp_path / "started"
    processes = install_fake_start(monkeypatch, [fake_worker_script(delay=0.4, marker=marker)])

    async def run():
        service = NERService(Settings(ner_max_concurrent_jobs=1, ner_max_queued_jobs=0))
        try:
            request = asyncio.create_task(service.detect_pages(["first"]))
            await wait_for_marker(marker)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            with pytest.raises(NERBusyError):
                await service.detect_pages(["next"])
            async with asyncio.timeout(5):
                while service._tasks:
                    await asyncio.sleep(0.01)
            assert await service.detect_pages(["next"]) == [[]]
            assert len(processes) == 1 and service._slots[0].process is processes[0]
        finally:
            await service.aclose()
        assert processes[0].returncode is not None

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_concurrent_jobs_use_separate_bounded_worker_processes(monkeypatch):
    processes = install_fake_start(monkeypatch, [fake_worker_script(delay=0.4)])

    async def run():
        service = NERService(Settings(ner_max_concurrent_jobs=2, ner_max_queued_jobs=0))
        try:
            requests = [asyncio.create_task(service.detect_pages([str(index)])) for index in range(2)]
            async with asyncio.timeout(5):
                while len(processes) < 2:
                    await asyncio.sleep(0.01)
            assert len({process.pid for process in processes}) == 2
            with pytest.raises(NERBusyError):
                await service.detect_pages(["over-capacity"])
            assert await asyncio.gather(*requests) == [[[]], [[]]]
        finally:
            await service.aclose()
        assert all(process.returncode is not None for process in processes)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_invalid_worker_response_is_sanitized_and_worker_is_replaced(monkeypatch):
    invalid = """
import json, sys
json.loads(sys.stdin.readline())
print('{"status":"ready"}', flush=True)
sys.stdin.readline()
print('not-json', flush=True)
"""
    processes = install_fake_start(monkeypatch, [invalid, fake_worker_script(delay=0)])

    async def run():
        service = NERService()
        try:
            with pytest.raises(NERProcessingError) as caught:
                await service.detect_pages(["private name"])
            assert "private name" not in str(caught.value)
            assert processes[0].returncode is not None
            assert await service.detect_pages(["next"]) == [[]]
            assert len(processes) == 2
        finally:
            await service.aclose()
        assert all(process.returncode is not None for process in processes)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_health_remains_responsive_while_ner_worker_is_busy(monkeypatch, tmp_path):
    marker = tmp_path / "started"
    processes = install_fake_start(monkeypatch, [fake_worker_script(delay=1, marker=marker)])
    service = NERService(Settings(ner_job_timeout_seconds=10))
    app = FastAPI()
    app.include_router(actual_app.router)

    @app.post("/_test_ner")
    async def run_ner():
        return {"pages": len(await service.detect_pages(["name"]))}

    async def run():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                request = asyncio.create_task(client.post("/_test_ner"))
                await wait_for_marker(marker)
                health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
                assert health.status_code == 200 and health.json() == {"status": "ok"}
                assert not request.done()
                assert (await request).json() == {"pages": 1}
        finally:
            await service.aclose()
        assert processes[0].returncode is not None

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="NER worker supervision requires POSIX")
def test_shutdown_kills_unresponsive_started_worker(monkeypatch, tmp_path):
    marker = tmp_path / "started"
    processes = install_fake_start(monkeypatch, [fake_worker_script(delay=30, ignore_sigterm=True, marker=marker)])

    async def run():
        service = NERService(Settings(ner_job_timeout_seconds=60, ner_shutdown_timeout_seconds=0.05))
        request = asyncio.create_task(service.detect_pages(["name"]))
        await wait_for_marker(marker)
        await asyncio.wait_for(service.aclose(), timeout=5)
        assert isinstance((await asyncio.gather(request, return_exceptions=True))[0], asyncio.CancelledError)
        assert processes[0].returncode is not None
        assert not service._tasks

    asyncio.run(run())
