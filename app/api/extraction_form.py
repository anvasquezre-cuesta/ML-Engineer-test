"""Parse the extraction multipart incrementally with explicit part limits."""

import asyncio
from contextlib import aclosing

from fastapi import Request
from starlette.datastructures import FormData
from starlette.formparsers import MultiPartException, MultiPartParser, parse_options_header

from app.core.config import Settings
from app.services.extraction_input import NamesLimitError
from app.services.ocr_service import PDFTooLargeError


class InvalidMultipartError(ValueError):
    """The extraction multipart is malformed or has unexpected parts."""


class _TextPartTooLarge(MultiPartException):
    pass


class _FilePartTooLarge(MultiPartException):
    pass


class _ExtractionMultipartParser(MultiPartParser):
    """Enforce part sizes while parsing and require a terminating boundary."""

    def __init__(self, headers, stream, settings: Settings, *, max_fields: int = 1):
        super().__init__(headers, stream, max_files=1, max_fields=max_fields, max_part_size=settings.max_names_bytes)
        self.file_limit = settings.max_upload_bytes
        self.file_bytes = 0
        self.complete = False

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        size = end - start
        if self._current_part.file is None:
            if len(self._current_part.data) + size > self.max_part_size:
                raise _TextPartTooLarge("Text field too large")
        else:
            self.file_bytes += size
            if self.file_bytes > self.file_limit:
                raise _FilePartTooLarge("File too large")
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self.complete = True


async def close_extraction_form(form: FormData) -> None:
    """Do not leave an uploaded file open if its caller is cancelled."""
    task = asyncio.create_task(form.close())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


async def parse_extraction_form(request: Request, settings: Settings, *, max_fields: int = 1) -> FormData:
    """Parse once; the caller owns and must close the returned form and its file."""
    media_type, _ = parse_options_header(request.headers.get("content-type", ""))
    if media_type.lower() != b"multipart/form-data":
        raise InvalidMultipartError("Expected multipart form data")
    async with aclosing(request.stream()) as stream:
        parser = _ExtractionMultipartParser(request.headers, stream, settings, max_fields=max_fields)
        try:
            form = await parser.parse()
        except _TextPartTooLarge:
            raise NamesLimitError("Names field exceeds its byte limit") from None
        except _FilePartTooLarge:
            raise PDFTooLargeError("PDF exceeds its byte limit") from None
        except MultiPartException:
            raise InvalidMultipartError("Invalid multipart form") from None
        if not parser.complete:
            # python-multipart.finalize() does not reject a missing final boundary.
            # Some opened files may not have been added to FormData yet.
            try:
                await close_extraction_form(form)
            finally:
                for file in parser._files_to_close_on_error:
                    file.close()
            raise InvalidMultipartError("Incomplete multipart form")
        return form
