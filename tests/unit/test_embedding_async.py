import asyncio
from pathlib import Path
import sys

import pytest

from app.core.config import Settings
from app.services.embedding_async import EmbeddingService, EmbeddingTimeoutError
from app.services.embedding_worker import prepare
from app.services.chunking_service import ChunkingLimitError
from app.services.embedding_service import EmbeddingProcessingError


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("query", [False, True])
def test_slow_worker_is_terminated_and_temporaries_removed(monkeypatch, cancel, query):
    original = asyncio.create_subprocess_exec
    processes = []
    async def slow_worker(*args, **kwargs):
        result = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        processes.append(result)
        return result
    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_worker)
    async def run():
        service = EmbeddingService(Settings(embedding_job_timeout_seconds=0.1 if not cancel else 10))
        task = asyncio.create_task(service.embed_query("question") if query else service.prepare(["text"]))
        while not processes:
            await asyncio.sleep(0)
        directory = Path(service._directory.name)
        if cancel: task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else EmbeddingTimeoutError):
            await task
        assert processes[0].returncode is not None and not directory.exists()
        assert service._process is None and not service._busy
        await service.aclose()
    asyncio.run(run())


def test_worker_enforces_total_chunk_limit_across_pages():
    class Tokenizer:
        def encode(self, text, *, add_special_tokens, truncation):
            tokens = list(range(len(text.split())))
            return [100, *tokens, 101] if add_special_tokens else tokens
    class Model:
        tokenizer = Tokenizer()
        def encode(self, *args, **kwargs):
            raise AssertionError("Over-limit document was embedded")
    config = Settings(ingest_max_chunks=1).model_dump()
    with pytest.raises(ChunkingLimitError):
        prepare(Model(), {"pages": ["first page", "second page"]}, config)


def test_query_rejected_while_ingestion_is_busy_without_cancelling_it(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def slow_worker(*args, **kwargs):
        process = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_worker)

    async def run():
        service = EmbeddingService(Settings(embedding_job_timeout_seconds=10))
        task = asyncio.create_task(service.prepare(["text"]))
        try:
            while not processes:
                await asyncio.sleep(0)
            with pytest.raises(EmbeddingProcessingError, match="not available"):
                await service.embed_query("question")
            assert not task.done() and processes[0].returncode is None
        finally:
            await service.aclose()
        assert task.cancelled() and processes[0].returncode is not None
    asyncio.run(run())
