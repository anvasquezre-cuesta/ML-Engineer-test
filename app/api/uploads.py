from fastapi import UploadFile

from app.core.errors import InvalidUpload


async def read_pdf(upload: UploadFile, max_mb: int) -> bytes:
    """Read the upload into memory, rejecting empty, oversized, or non-PDF content."""
    limit = max_mb * 1024 * 1024
    chunks = []
    size = 0
    while chunk := await upload.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise InvalidUpload(f"file exceeds {max_mb} MB", 413)
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise InvalidUpload("empty file")
    if not data.startswith(b"%PDF-"):  # judge by content, not by extension
        raise InvalidUpload("file is not a PDF", 415)
    return data
