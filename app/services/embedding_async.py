"""One lazy, persistent supervised embedding worker per application process."""

import asyncio
from dataclasses import dataclass
import json
import math
import sys
import tempfile

from app.core.config import Settings
from app.core.embedding_model import MODEL_DIMENSIONS
from app.core.worker_environment import worker_environment
from app.services.ask_input import normalize_question
from app.services.chunking_service import ChunkingError, ChunkingLimitError, TextChunk
from app.services.embedding_service import EmbeddingInputError, EmbeddingModelUnavailableError, EmbeddingProcessingError
from app.services.ingestion_ledger import PageRecord
from app.services.ocr_service import _finish_cancelled_task, _terminate_process_group

MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class EmbeddingTimeoutError(EmbeddingProcessingError):
    pass


@dataclass(frozen=True)
class PreparedDocument:
    chunks: list[TextChunk]
    pages: list[PageRecord]
    vectors: list[list[float]]


class EmbeddingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._process = None
        self._directory = None
        self._busy = False
        self._closing = False
        self._task = None

    async def _receive(self, *, query=False):
        assert self._process.stdout is not None
        try:
            line = await self._process.stdout.readline()
            if not line or len(line) > MAX_MESSAGE_BYTES:
                raise ValueError("Invalid response")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Invalid message")
        except (OSError, ValueError, RecursionError):
            raise EmbeddingProcessingError("Embedding worker returned an invalid response") from None
        if message.get("status") == "model_unavailable":
            raise EmbeddingModelUnavailableError("Pinned local model is unavailable")
        if message.get("status") == "input_error":
            if query:
                raise EmbeddingInputError("Question cannot be embedded within the model token budget")
            raise ChunkingError("Document text cannot be chunked within the model budget")
        if message.get("status") == "limit_error":
            raise ChunkingLimitError("Document exceeds the configured preparation limits")
        if message.get("status") not in {"ready", "ok"}:
            raise EmbeddingProcessingError("Embedding worker failed")
        return message

    async def _send(self, message):
        assert self._process.stdin is not None
        encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ChunkingLimitError("Document exceeds the worker input limit")
        self._process.stdin.write(encoded)
        await self._process.stdin.drain()

    async def prepare(self, pages: list[str]) -> PreparedDocument:
        if (not pages or len(pages) > self.settings.max_pdf_pages or any(not isinstance(p, str) for p in pages)
                or sum(map(len, pages)) > self.settings.ingest_max_document_chars):
            raise ChunkingLimitError("Invalid document text or size")
        return await self._run({"pages": pages}, pages=pages)

    async def embed_query(self, question: str) -> list[float]:
        question = normalize_question(question)
        return await self._run({"operation": "query", "question": question})

    async def _run(self, request, *, pages=None):
        if self._closing or self._busy:
            raise EmbeddingProcessingError("Embedding worker is not available")
        self._busy, self._task = True, asyncio.current_task()
        try:
            async with asyncio.timeout(self.settings.embedding_job_timeout_seconds):
                if self._process is None:
                    self._directory = tempfile.TemporaryDirectory(prefix="embedding-worker-")
                    start = asyncio.create_task(asyncio.create_subprocess_exec(
                        sys.executable, "-m", "app.services.embedding_worker",
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
                        limit=MAX_MESSAGE_BYTES,
                        env=worker_environment(TMPDIR=self._directory.name, HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false"),
                    ))
                    try:
                        self._process = await asyncio.shield(start)
                    except asyncio.CancelledError:
                        await _finish_cancelled_task(start)
                        self._process = start.result()
                        raise
                    await self._send(self.settings.model_dump(include={
                        "embedding_model_dir", "embedding_batch_size", "max_pdf_pages", "ingest_chunk_tokens",
                        "ingest_overlap_tokens", "ingest_max_page_chars", "ingest_max_document_chars", "ingest_max_chunks",
                        "embedding_query_max_tokens",
                    }))
                    if (await self._receive())["status"] != "ready":
                        raise EmbeddingProcessingError("Embedding worker did not initialize")
                await self._send(request)
                message = await self._receive(query=pages is None)
                if pages is None:
                    vector = message["vector"]
                    if (not isinstance(vector, list) or len(vector) != MODEL_DIMENSIONS
                            or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
                            or not any(vector)):
                        raise EmbeddingProcessingError("Invalid query embedding")
                    return vector
                chunks = [TextChunk(**item) for item in message["chunks"]]
                records = [PageRecord(**item) for item in message["pages"]]
                vectors = message["vectors"]
                if (len(records) != len(pages) or len(chunks) != len(vectors)
                        or len(chunks) > self.settings.ingest_max_chunks
                        or any(len(v) != 384 or not all(math.isfinite(x) for x in v) or not any(v) for v in vectors)):
                    raise EmbeddingProcessingError("Invalid prepared document")
                for chunk in chunks:
                    if (not 0 <= chunk.page_number < len(pages)
                            or pages[chunk.page_number][chunk.char_start:chunk.char_end] != chunk.text
                            or not chunk.text.strip() or chunk.token_count > self.settings.ingest_chunk_tokens):
                        raise EmbeddingProcessingError("Invalid page-local fragment")
                return PreparedDocument(chunks, records, vectors)
        except TimeoutError:
            await self._reset()
            raise EmbeddingTimeoutError("Embedding preparation timed out") from None
        except (OSError, KeyError, TypeError, ValueError) as error:
            await self._reset()
            if isinstance(error, (ChunkingError, EmbeddingInputError)):
                raise
            raise EmbeddingProcessingError("Embedding worker failed or returned inconsistent data") from None
        except BaseException:
            await self._reset()
            raise
        finally:
            self._busy, self._task = False, None

    async def _reset(self):
        process, self._process = self._process, None
        try:
            if process is not None:
                task = asyncio.create_task(_terminate_process_group(process))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await _finish_cancelled_task(task)
                    raise
        finally:
            if self._directory is not None:
                self._directory.cleanup()
                self._directory = None

    async def aclose(self):
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._reset()
