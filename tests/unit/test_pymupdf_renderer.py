"""PyMuPDF renderer: every page, displayed geometry, unreadable input."""

import pymupdf
import pytest

from app.adapters.pymupdf import page_renderer
from app.domain import errors


def portrait_then_rotated_pdf() -> bytes:
    """Returns an A4 page followed by an A4 page stored with ``/Rotate 90``.

    Returns:
        The PDF content.
    """
    with pymupdf.open() as document:
        document.new_page(width=595, height=842)
        document.new_page(width=595, height=842).set_rotation(90)
        return bytes(document.tobytes())


def test_every_page_is_rendered_with_its_displayed_geometry() -> None:
    pages = page_renderer.PyMuPdfRenderer(dpi=144).render(
        portrait_then_rotated_pdf()
    )

    assert [
        (p.page_number, p.width_pt, p.height_pt, p.width_px, p.height_px)
        for p in pages
    ] == [(0, 595.0, 842.0, 1190, 1684), (1, 842.0, 595.0, 1684, 1190)]
    assert all(len(p.pixels) == p.width_px * p.height_px for p in pages)


def test_content_that_is_not_a_readable_pdf_is_rejected() -> None:
    with pytest.raises(errors.OcrUnreadableError):
        page_renderer.PyMuPdfRenderer(dpi=72).render(
            b"%PDF-1.7\nnot really a pdf"
        )
