"""Request parsing helpers shared by the routers.

They take plain streams and strings, not FastAPI objects, so they are tested
without HTTP. Routers pass ``UploadFile.file`` and the raw ``names`` form field.
"""

from typing import BinaryIO

from pydantic import TypeAdapter, ValidationError

from app.domain.errors import DocumentTooLarge, InvalidRequest
from app.models.schemas import NamePair

READ_CHUNK_BYTES = 1024 * 1024

_NAMES = TypeAdapter(list[NamePair])


def read_upload(stream: BinaryIO, max_bytes: int) -> bytes:
    """Read at most ``max_bytes``; reading one byte more means the file is too large."""
    buffer = bytearray()
    while chunk := stream.read(min(READ_CHUNK_BYTES, max_bytes + 1 - len(buffer))):
        buffer += chunk
        if len(buffer) > max_bytes:
            raise DocumentTooLarge(f"The file exceeds the {max_bytes}-byte limit.")
    return bytes(buffer)


def parse_names(raw: str) -> list[NamePair]:
    try:
        return _NAMES.validate_json(raw)
    except ValidationError as exc:
        raise InvalidRequest(
            '\'names\' must be a JSON list of {"first_name", "last_name"} objects '
            f"({exc.error_count()} validation error(s))."
        ) from exc
