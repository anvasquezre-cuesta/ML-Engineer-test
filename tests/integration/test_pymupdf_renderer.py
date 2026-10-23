"""The real PyMuPDF adapter on PDFs built in memory (no Tesseract needed)."""

import pymupdf
import pytest

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.domain.errors import InvalidDocument


def _pdf(pages: int, rotate_last: int = 0) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    if rotate_last:
        doc[-1].set_rotation(rotate_last)
    return bytes(doc.tobytes())


def test_page_count() -> None:
    assert PyMuPDFRenderer().page_count(_pdf(3)) == 3


def test_render_yields_every_page_in_order_with_sizes_in_points() -> None:
    pages = list(PyMuPDFRenderer().render(_pdf(3), dpi=150))

    assert [p.index for p in pages] == [0, 1, 2]
    first = pages[0]
    assert (first.width_pt, first.height_pt, first.dpi) == (612.0, 792.0, 150)
    assert (first.width_px, first.height_px) == (1275, 1650)
    assert len(first.pixels) == first.width_px * first.height_px * 3  # RGB, no padding


def test_render_reports_page_rotation() -> None:
    pages = list(PyMuPDFRenderer().render(_pdf(2, rotate_last=90), dpi=72))

    assert [p.rotation for p in pages] == [0, 90]


@pytest.mark.parametrize("data", [b"%PDF-1.7 garbage", b"%PDF-", b"not a pdf at all"])
def test_corrupt_pdf_is_an_invalid_document(data: bytes) -> None:
    with pytest.raises(InvalidDocument, match="corrupt"):
        PyMuPDFRenderer().page_count(data)


def test_encrypted_pdf_is_an_invalid_document() -> None:
    doc = pymupdf.open()
    doc.new_page()
    encrypted = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")

    with pytest.raises(InvalidDocument, match="encrypted"):
        PyMuPDFRenderer().page_count(encrypted)
