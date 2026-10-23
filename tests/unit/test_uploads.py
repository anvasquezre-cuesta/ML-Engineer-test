import io

import pytest

from app.api.uploads import READ_CHUNK_BYTES, parse_names, read_upload
from app.domain.errors import DocumentTooLarge, InvalidRequest


class RecordingStream(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.requested: list[int] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.requested.append(-1 if size is None else size)
        return super().read(size)


def test_reads_a_file_under_the_limit() -> None:
    assert read_upload(io.BytesIO(b"%PDF-abc"), max_bytes=100) == b"%PDF-abc"


def test_a_file_exactly_at_the_limit_is_accepted() -> None:
    assert len(read_upload(io.BytesIO(b"x" * 10), max_bytes=10)) == 10


def test_one_byte_over_the_limit_is_rejected() -> None:
    with pytest.raises(DocumentTooLarge):
        read_upload(io.BytesIO(b"x" * 11), max_bytes=10)


def test_never_reads_more_than_limit_plus_one_byte() -> None:
    stream = RecordingStream(b"x" * (5 * READ_CHUNK_BYTES))

    with pytest.raises(DocumentTooLarge):
        read_upload(stream, max_bytes=READ_CHUNK_BYTES + 10)

    assert stream.tell() == READ_CHUNK_BYTES + 11
    assert all(0 < size <= READ_CHUNK_BYTES for size in stream.requested)


def test_empty_stream_returns_empty_bytes() -> None:
    # Emptiness is a document error, decided by the loader, not by the reader.
    assert read_upload(io.BytesIO(b""), max_bytes=10) == b""


def test_parse_names_accepts_the_documented_shape() -> None:
    names = parse_names('[{"first_name": "María", "last_name": "González"}]')

    assert [(n.first_name, n.last_name) for n in names] == [("María", "González")]


def test_parse_names_accepts_an_empty_list() -> None:
    assert parse_names("[]") == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"first_name": "A", "last_name": "B"}',  # an object, not a list
        '[{"first_name": "A"}]',  # missing last_name
        '[{"first_name": "", "last_name": "B"}]',  # empty first_name
        '["Ada Lovelace"]',  # strings, not objects
    ],
)
def test_parse_names_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(InvalidRequest):
        parse_names(raw)
