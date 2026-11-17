import asyncio
import logging
import threading

import pytest

from app.core.config import Settings
from app.models.document import OCRDocument, OCRPage, OCRWord, WordBox
from app.models.extraction import PersonSpan
from app.models.schemas import NamePair
from app.services.extraction_service import ExtractionLimitError, ExtractionService
from app.services.ner_service import NERProcessingError


def make_document():
    text = "Alice Smith"
    words = (
        OCRWord("Alice", WordBox(10, 10, 30, 10), 0, 5, 1, 1, 1, 90),
        OCRWord("Smith", WordBox(45, 10, 25, 10), 6, 11, 1, 1, 1, 90),
    )
    return OCRDocument((OCRPage(0, 200, 200, text, words),))


class FakeOCR:
    async def extract_stream_async(self, stream):
        return make_document()


class FakeNER:
    def __init__(self, result):
        self.result = result

    async def detect_pages(self, pages):
        return self.result


def test_invalid_location_is_not_invented_or_fuzzy_matched(caplog):
    service = ExtractionService(FakeOCR(), FakeNER([[PersonSpan("Other Name", 0, 10)]]), Settings())
    response = asyncio.run(service.extract(None, [NamePair(first_name="Other", last_name="Name")]))
    assert response.extracted_names == [] and response.fuzzy_matches == []
    assert "count=1" in caplog.text and "Other Name" not in caplog.text


def test_inconsistent_ner_page_count_is_an_error():
    service = ExtractionService(FakeOCR(), FakeNER([]), Settings())
    with pytest.raises(NERProcessingError):
        asyncio.run(service.extract(None, []))


def test_entity_limit_is_inclusive():
    span = PersonSpan("Alice Smith", 0, 11)
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings(max_extracted_names=1))
    assert len(asyncio.run(service.extract(None, [])).extracted_names) == 1
    service = ExtractionService(FakeOCR(), FakeNER([[span, span]]), Settings(max_extracted_names=1))
    with pytest.raises(ExtractionLimitError):
        asyncio.run(service.extract(None, []))


def test_long_entity_is_rejected_before_assembly():
    service = ExtractionService(FakeOCR(), FakeNER([[PersonSpan("Alice Smith", 0, 11)]]), Settings(max_name_chars=10))
    with pytest.raises(ExtractionLimitError):
        asyncio.run(service.extract(None, []))


def test_normalized_character_work_limit_is_inclusive():
    span = PersonSpan("Alice Smith", 0, 11)
    names = [NamePair(first_name="Alice", last_name="Smith")]
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings(max_fuzzy_work_units=121))
    assert len(asyncio.run(service.extract(None, names)).fuzzy_matches) == 1
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings(max_fuzzy_work_units=120))
    with pytest.raises(ExtractionLimitError):
        asyncio.run(service.extract(None, names))


def test_cancelled_assembly_waits_until_thread_releases_resources(monkeypatch):
    started, finish = threading.Event(), threading.Event()
    span = PersonSpan("Alice Smith", 0, 11)
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings())
    original = service._assemble

    def slow_assembly(*args):
        started.set()
        if not finish.wait(timeout=5):
            raise RuntimeError("test did not release assembly")
        return original(*args)

    monkeypatch.setattr(service, "_assemble", slow_assembly)

    async def run():
        task = asyncio.create_task(service.extract(None, []))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            finish.set()

    asyncio.run(run())


def test_recovery_logs_counts_without_names(caplog):
    span = PersonSpan("Alice Smith", 0, 11)
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings(ner_name_recovery_passes=1))
    with caplog.at_level(logging.INFO, logger="app.services.extraction_service"):
        asyncio.run(service.extract(None, []))
    assert "Name recovery: passes=1" in caplog.text and "Alice" not in caplog.text


def test_cancelled_enabled_recovery_waits_for_the_assembly_thread(monkeypatch):
    from app.services import extraction_service

    started, finish = threading.Event(), threading.Event()
    original = extraction_service.recover_names

    def slow_recovery(*args, **kwargs):
        started.set()
        if not finish.wait(timeout=5):
            raise RuntimeError("test did not release recovery")
        return original(*args, **kwargs)

    monkeypatch.setattr(extraction_service, "recover_names", slow_recovery)
    span = PersonSpan("Alice Smith", 0, 11)
    service = ExtractionService(FakeOCR(), FakeNER([[span]]), Settings(ner_name_recovery_passes=1))

    async def run():
        task = asyncio.create_task(service.extract(None, []))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            finish.set()

    asyncio.run(run())
