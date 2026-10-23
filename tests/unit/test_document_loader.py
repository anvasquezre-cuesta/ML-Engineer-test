import hashlib

import pytest

from app.domain.errors import DocumentTooLarge, InvalidDocument, UnsupportedMediaType
from app.services.documents import DocumentLoader, document_id
from tests.fakes import FakeRenderer, blank_page

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _loader(pages: int = 1, max_bytes: int = 1000, max_pages: int = 5) -> DocumentLoader:
    renderer = FakeRenderer([blank_page(i) for i in range(pages)])
    return DocumentLoader(renderer, max_bytes=max_bytes, max_pages=max_pages)


def test_valid_pdf_gets_its_sha256_as_doc_id_and_page_count() -> None:
    data = b"%PDF-1.7 minimal"

    document = _loader(pages=3).load(data)

    assert document.doc_id == hashlib.sha256(data).hexdigest()
    assert document.page_count == 3
    assert document.data == data


def test_empty_file_is_an_invalid_document() -> None:
    with pytest.raises(InvalidDocument, match="empty"):
        _loader().load(b"")


def test_rejects_non_pdf_by_content_not_name() -> None:
    renderer = FakeRenderer([blank_page(0)])
    loader = DocumentLoader(renderer, max_bytes=1000, max_pages=5)

    with pytest.raises(UnsupportedMediaType):
        loader.load(PNG_BYTES)
    assert renderer.page_count_calls == 0  # rejected before any parsing


def test_oversized_bytes_are_rejected() -> None:
    with pytest.raises(DocumentTooLarge):
        _loader(max_bytes=10).load(b"%PDF-" + b"x" * 10)


def test_too_many_pages_is_rejected() -> None:
    with pytest.raises(DocumentTooLarge, match="6 pages"):
        _loader(pages=6, max_pages=5).load(b"%PDF-1.7")


def test_pdf_without_pages_is_invalid() -> None:
    with pytest.raises(InvalidDocument, match="no pages"):
        _loader(pages=0).load(b"%PDF-1.7")


def test_document_id_differs_for_different_content() -> None:
    assert document_id(b"%PDF-a") != document_id(b"%PDF-b")
    assert document_id(b"%PDF-a") == document_id(b"%PDF-a")
