"""Render PDF pages and preserve Tesseract words and their PDF coordinates.

Coordinates are in points, relative to the top-left of the unrotated crop box.
This is the coordinate convention used by PyMuPDF for unrotated page content.
Page indices are zero-based. Each page's character offsets address its own text.
"""

import asyncio
from contextlib import closing
import json
import logging
import math
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Any, Protocol

import anyio
import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output

from app.core.config import Settings, get_settings
from app.core.worker_environment import worker_environment
from app.models.document import OCRDocument, OCRPage, OCRWord, WordBox

logger = logging.getLogger(__name__)


class InvalidPDFError(ValueError):
    """The input is empty, invalid, encrypted or exceeds the page limit."""


class PDFTooLargeError(ValueError):
    """The input exceeds the configured byte limit."""


class PDFPageTooLargeError(InvalidPDFError):
    """A page exceeds the configured rendered-pixel limit."""


class PDFPageCountError(InvalidPDFError):
    """The document exceeds the configured number of pages."""


class OCRProcessingError(RuntimeError):
    """A page could not be rendered or processed by the OCR engine."""


class OCRBusyError(RuntimeError):
    """OCR admission is full or a queued job waited too long."""


class OCRDocumentTimeoutError(OCRProcessingError):
    """The entire document exceeded its processing deadline."""


class OCRUploadTimeoutError(OCRProcessingError):
    """The upload stream exceeded its reading deadline."""


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


def _validate_pdf_size(pdf_bytes: bytes, max_upload_bytes: int) -> None:
    if not pdf_bytes:
        raise InvalidPDFError("The PDF is empty")
    if len(pdf_bytes) > max_upload_bytes:
        raise PDFTooLargeError("The PDF exceeds the configured size limit")


def _word_box(page: pymupdf.Page, pix: pymupdf.Pixmap, scale: float, row: dict[str, Any], normalized: bool) -> WordBox | None:
    """Map normalized-image pixels back through rendering to PDF coordinates."""
    left, top = float(row["left"]), float(row["top"])
    width, height = float(row["width"]), float(row["height"])
    if width <= 0 or height <= 0:
        return None

    right, bottom = left + width, top + height
    if normalized and page.rotation == 90:
        left, top, right, bottom = pix.width - bottom, left, pix.width - top, right
    elif normalized and page.rotation == 180:
        left, top, right, bottom = pix.width - right, pix.height - bottom, pix.width - left, pix.height - top
    elif normalized and page.rotation == 270:
        left, top, right, bottom = top, pix.height - right, bottom, pix.height - left
    pixels = pymupdf.Rect(pix.x + left, pix.y + top, pix.x + right, pix.y + bottom)
    rect = pixels * ~pymupdf.Matrix(scale, scale) * page.derotation_matrix
    visible = page.rect * page.derotation_matrix
    rect &= visible
    if rect.is_empty or rect.is_infinite:
        return None
    return WordBox(rect.x0, rect.y0, rect.width, rect.height)


def _mean_confidence(data: dict[str, list]) -> float:
    scores = [float(score) for text, score in zip(data["text"], data["conf"]) if text.strip() and float(score) >= 0]
    return sum(scores) / len(scores) if scores else 0.0


class OCRService:
    """Extract a document in a single pass with bounded PDF and OCR inputs."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings if settings is not None else get_settings()
        self._process_limiter = anyio.Semaphore(self.settings.ocr_max_concurrent_jobs)
        self._admission = anyio.Semaphore(
            self.settings.ocr_max_concurrent_jobs + self.settings.ocr_max_queued_jobs
        )
        self._tasks: set[asyncio.Task] = set()
        self._started: set[asyncio.Task] = set()
        self._closing = False

    def _admit(self) -> None:
        if self._closing:
            raise OCRBusyError("OCR service is shutting down")
        try:
            self._admission.acquire_nowait()
        except anyio.WouldBlock as exc:
            raise OCRBusyError("OCR capacity is full") from exc

    async def extract_async(self, pdf_bytes: bytes) -> OCRDocument:
        """Run OCR in a supervised process; reuse this service to share limits."""
        _validate_pdf_size(pdf_bytes, self.settings.max_upload_bytes)
        self._admit()
        return await self._schedule(pdf_bytes, is_bytes=True)

    async def extract_file_async(self, pdf_path: str | Path) -> OCRDocument:
        """Read and process a local PDF in a supervised worker process."""
        self._admit()
        return await self._schedule(str(pdf_path), is_bytes=False)

    async def extract_stream_async(self, stream: AsyncReadable) -> OCRDocument:
        """Reserve capacity before reading a bounded async upload stream."""
        self._admit()
        scheduled = False
        try:
            data = bytearray()
            try:
                async with asyncio.timeout(self.settings.ocr_upload_timeout_seconds):
                    while True:
                        chunk = await stream.read(min(64 * 1024, self.settings.max_upload_bytes + 1 - len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > self.settings.max_upload_bytes:
                            raise PDFTooLargeError("The PDF exceeds the configured size limit")
            except TimeoutError as exc:
                raise OCRUploadTimeoutError("OCR upload read timed out") from exc
            _validate_pdf_size(data, self.settings.max_upload_bytes)
            payload = await _run_blocking(bytes, data)
            scheduled = True
            return await self._schedule(payload, is_bytes=True)
        finally:
            if not scheduled:
                self._admission.release()

    async def _schedule(self, source: bytes | str, *, is_bytes: bool) -> OCRDocument:
        if self._closing:
            self._admission.release()
            raise OCRBusyError("OCR service is shutting down")
        try:
            task = asyncio.create_task(self._run_admitted(source, is_bytes=is_bytes))
        except BaseException:
            self._admission.release()
            raise
        self._tasks.add(task)

        def finished(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            self._started.discard(done)
            self._admission.release()
            if not done.cancelled():
                done.exception()  # Consume errors even when the caller has disconnected.

        task.add_done_callback(finished)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task not in self._started:
                task.cancel()
            raise

    async def _run_admitted(self, source: bytes | str, *, is_bytes: bool) -> OCRDocument:
        try:
            with anyio.fail_after(self.settings.ocr_queue_timeout_seconds):
                await self._process_limiter.acquire()
        except TimeoutError as exc:
            raise OCRBusyError("OCR queue wait timed out") from exc
        try:
            task = asyncio.current_task()
            assert task is not None
            self._started.add(task)
            logger.info("OCR job started")
            try:
                async with asyncio.timeout(self.settings.ocr_document_timeout_seconds):
                    result = await self._execute_job(source, is_bytes=is_bytes)
                    logger.info("OCR job completed: pages=%d", len(result.pages))
                    return result
            except TimeoutError as exc:
                raise OCRDocumentTimeoutError("OCR document deadline exceeded") from exc
        finally:
            self._process_limiter.release()

    async def _execute_job(self, source: bytes | str, *, is_bytes: bool) -> OCRDocument:
        if os.name != "posix":
            raise OCRProcessingError("Supervised OCR workers require a POSIX platform")
        with tempfile.TemporaryDirectory(prefix="ocr-job-") as directory:
            workdir = Path(directory)
            if is_bytes:
                input_path = workdir / "input.pdf"
                await _run_blocking(input_path.write_bytes, source)
            else:
                input_path = Path(source)
            result_path = workdir / "result.json"
            settings = self.settings.model_dump(include={
                "max_upload_bytes", "max_pdf_pages", "max_page_pixels", "ocr_dpi",
                "ocr_languages", "ocr_timeout_seconds", "ocr_orientation_min_confidence",
            })
            env = worker_environment(TMPDIR=directory)
            try:
                process = await _start_worker(
                    sys.executable, "-m", "app.services.ocr_worker",
                    str(input_path), str(result_path), json.dumps(settings),
                    env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                raise OCRProcessingError("Could not start OCR worker") from exc
            try:
                await process.wait()
            finally:
                await _terminate_process_group(process)
            if process.returncode != 0 or not result_path.is_file():
                logger.error("OCR worker failed: exit_code=%s", process.returncode)
                raise OCRProcessingError("OCR worker failed unexpectedly")
            try:
                response = await _run_blocking(_read_worker_result, result_path)
            except (OSError, ValueError) as exc:
                raise OCRProcessingError("OCR worker returned an invalid result") from exc
            if response["status"] == "error":
                error_type = {
                    "InvalidPDFError": InvalidPDFError,
                    "PDFTooLargeError": PDFTooLargeError,
                    "PDFPageTooLargeError": PDFPageTooLargeError,
                    "PDFPageCountError": PDFPageCountError,
                    "OCRProcessingError": OCRProcessingError,
                    "FileNotFoundError": FileNotFoundError,
                }.get(response["type"], OCRProcessingError)
                raise error_type(response["message"])
            try:
                return await _run_blocking(_document_from_dict, response["document"])
            except (KeyError, TypeError, ValueError) as exc:
                raise OCRProcessingError("OCR worker returned an invalid document") from exc

    async def aclose(self) -> None:
        """Stop admission, allow jobs to finish briefly, then clean up workers."""
        self._closing = True
        tasks = set(self._tasks)
        for task in tasks - self._started:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.settings.ocr_shutdown_timeout_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def extract(self, pdf_bytes: bytes) -> OCRDocument:
        _validate_pdf_size(pdf_bytes, self.settings.max_upload_bytes)

        try:
            document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except (pymupdf.FileDataError, ValueError) as exc:
            raise InvalidPDFError("The input is not a valid PDF") from exc

        with document:
            if not document.is_pdf or document.needs_pass:
                raise InvalidPDFError("The input must be an unencrypted PDF")
            if document.page_count == 0:
                raise InvalidPDFError("The PDF contains no pages")
            if document.page_count > self.settings.max_pdf_pages:
                raise PDFPageCountError("The PDF exceeds the configured page limit")

            pages = tuple(self._extract_page(page) for page in document)
            return OCRDocument(pages=pages)

    def extract_file(self, pdf_path: str | Path) -> OCRDocument:
        # Bounded reads avoid loading an oversized file into memory first.
        with Path(pdf_path).open("rb") as source:
            pdf_bytes = source.read(self.settings.max_upload_bytes + 1)
        return self.extract(pdf_bytes)

    def _extract_page(self, page: pymupdf.Page) -> OCRPage:
        scale = self.settings.ocr_dpi / 72.0
        width, height = page.rect.width * scale, page.rect.height * scale
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            raise InvalidPDFError(f"Invalid dimensions on page {page.number}")
        # Include a pixel of rounding headroom on each axis before any allocation.
        if (math.ceil(width) + 1) * (math.ceil(height) + 1) > self.settings.max_page_pixels:
            raise PDFPageTooLargeError(f"Page {page.number} exceeds the rendered-pixel limit")
        try:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            with closing(Image.frombytes("RGB", (pix.width, pix.height), pix.samples)) as image:
                data = pytesseract.image_to_data(
                    image,
                    lang=self.settings.ocr_languages,
                    output_type=Output.DICT,
                    timeout=self.settings.ocr_timeout_seconds,
                )
                normalized = False
                if page.rotation and _mean_confidence(data) < self.settings.ocr_orientation_min_confidence:
                    with closing(image.rotate(page.rotation, expand=True)) as alternate:
                        alternate_data = pytesseract.image_to_data(
                            alternate,
                            lang=self.settings.ocr_languages,
                            output_type=Output.DICT,
                            timeout=self.settings.ocr_timeout_seconds,
                        )
                    if _mean_confidence(alternate_data) > _mean_confidence(data):
                        data = alternate_data
                        normalized = True
        except (pytesseract.TesseractError, OSError, RuntimeError, ValueError) as exc:
            raise OCRProcessingError(f"OCR failed on page {page.number}") from exc

        words: list[OCRWord] = []
        parts: list[str] = []
        offset = 0
        previous_line: tuple[int, int, int] | None = None
        for index, raw_text in enumerate(data["text"]):
            text = raw_text.strip()
            if not text:
                continue
            row = {key: values[index] for key, values in data.items()}
            box = _word_box(page, pix, scale, row, normalized)
            if box is None:
                continue
            line = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
            separator = "" if not words else (" " if line == previous_line else "\n")
            parts.append(separator)
            offset += len(separator)
            start = offset
            parts.append(text)
            offset += len(text)
            words.append(OCRWord(text, box, start, offset, *line, float(row["conf"])))
            previous_line = line

        visible = page.rect * page.derotation_matrix
        return OCRPage(page.number, visible.width, visible.height, "".join(parts), tuple(words))


async def _finish_cancelled_task(task):
    """Wait for supervised work even if its caller is cancelled repeatedly."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    if not task.cancelled():
        task.exception()  # Consume any failure; the original cancellation wins.


async def _run_blocking(function, *args):
    """Do not remove temporary files while a cancelled file operation is running."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _finish_cancelled_task(task)
        raise


async def _start_worker(*args, **kwargs) -> asyncio.subprocess.Process:
    """If startup is cancelled, obtain the process handle and clean its group."""
    task = asyncio.create_task(asyncio.create_subprocess_exec(*args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        process = await task
        await _terminate_process_group(process)
        raise


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    """Terminate both the worker and its Tesseract descendants on POSIX."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _read_worker_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _document_from_dict(data: dict) -> OCRDocument:
    pages = []
    for page in data["pages"]:
        words = tuple(
            OCRWord(**{**word, "box": WordBox(**word["box"])}) for word in page["words"]
        )
        pages.append(OCRPage(page["page_number"], page["width"], page["height"], page["text"], words))
    return OCRDocument(tuple(pages))


def extract_text_from_pdf(pdf_path: str) -> str:
    """Compatibility wrapper for callers needing the full OCR text."""
    return OCRService().extract_file(pdf_path).text


def get_word_bounding_boxes(pdf_path: str) -> list[dict]:
    """Compatibility wrapper returning one PDF-coordinate box per OCR word."""
    result = OCRService().extract_file(pdf_path)
    return [
        {"word": word.text, "page": page.page_number, "x": word.box.x,
         "y": word.box.y, "width": word.box.width, "height": word.box.height}
        for page in result.pages for word in page.words
    ]
