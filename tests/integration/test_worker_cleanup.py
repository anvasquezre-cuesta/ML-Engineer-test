"""Check supervised process cleanup with a controlled slow Tesseract command."""

import asyncio
import os
from pathlib import Path
import signal

import pytest

from app.core.config import Settings
from app.services.ocr_service import OCRBusyError, OCRDocumentTimeoutError, OCRService


def configure_slow_tesseract(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "tesseract.pid"
    executable = bin_dir / "tesseract"
    executable.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = "--version" ]; then exec /usr/bin/tesseract --version; fi\n'
        f'echo $$ > "{marker}"\n'
        'trap "" TERM\n'
        'exec sleep 30\n'
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    job_root = tmp_path / "jobs"
    job_root.mkdir()
    monkeypatch.setattr("app.services.ocr_service.tempfile.tempdir", str(job_root))
    return marker, job_root


def process_running(pid):
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return False
    try:
        state = next(line for line in status.read_text().splitlines() if line.startswith("State:"))
        return "Z" not in state.split()[1]
    except FileNotFoundError:
        return False


@pytest.mark.skipif(os.name != "posix" or not Path("/proc").exists(), reason="Linux process inspection required")
def test_direct_cancellation_then_shutdown_cleans_process_and_tempfiles(monkeypatch, tmp_path):
    marker, job_root = configure_slow_tesseract(monkeypatch, tmp_path)
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))

    async def run():
        service = OCRService(Settings(
            ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=0,
            ocr_shutdown_timeout_seconds=0.05,
        ))
        task = asyncio.create_task(service.extract_file_async(sample_dir / "company_memo.pdf"))
        pid = None
        try:
            async with asyncio.timeout(15):
                while not marker.exists():
                    await asyncio.sleep(0.02)
            pid = int(marker.read_text())
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert process_running(pid)
            with pytest.raises(OCRBusyError):
                await service.extract_async(b"other")
            await service.aclose()
            async with asyncio.timeout(5):
                while process_running(pid):
                    await asyncio.sleep(0.02)
            assert list(job_root.iterdir()) == []
        finally:
            await service.aclose()
            if pid and process_running(pid):
                os.kill(pid, signal.SIGKILL)

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix" or not Path("/proc").exists(), reason="Linux process inspection required")
def test_document_timeout_cleans_process_and_tempfiles(monkeypatch, tmp_path):
    marker, job_root = configure_slow_tesseract(monkeypatch, tmp_path)
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))

    async def run():
        service = OCRService(Settings(ocr_document_timeout_seconds=2))
        pid = None
        try:
            with pytest.raises(OCRDocumentTimeoutError):
                await service.extract_file_async(sample_dir / "company_memo.pdf")
            assert marker.exists(), "timeout occurred before Tesseract started"
            pid = int(marker.read_text())
            async with asyncio.timeout(5):
                while process_running(pid):
                    await asyncio.sleep(0.02)
            assert list(job_root.iterdir()) == []
        finally:
            await service.aclose()
            if pid and process_running(pid):
                os.kill(pid, signal.SIGKILL)

    asyncio.run(run())
