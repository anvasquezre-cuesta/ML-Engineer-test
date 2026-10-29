import pymupdf
import pytest

from app.domain.errors import PdfEncrypted, PdfUnreadable
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from tests.conftest import SAMPLE_PAGE_COUNTS, sample_bytes

pytestmark = pytest.mark.integration


def _encrypted_pdf() -> bytes:
    with pymupdf.open() as doc:
        doc.new_page()
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")


@pytest.mark.parametrize(("name", "pages"), SAMPLE_PAGE_COUNTS.items())
def test_probe_reports_page_count(name: str, pages: int) -> None:
    info = PyMuPdfRasterizer().probe(sample_bytes(name))

    assert info.page_count == pages
    assert info.encrypted is False


@pytest.mark.parametrize(("name", "pages"), SAMPLE_PAGE_COUNTS.items())
def test_render_yields_every_page_in_points(name: str, pages: int) -> None:
    images = list(PyMuPdfRasterizer().render(sample_bytes(name), dpi=72))

    assert [image.index for image in images] == list(range(pages))
    assert all((image.width_pt, image.height_pt) == (612.0, 792.0) for image in images)
    assert all(image.png.startswith(b"\x89PNG") for image in images)


@pytest.mark.parametrize("garbage", [b"hello world", b"%PDF-1.7 broken"])
def test_unparseable_bytes_are_unreadable(garbage: bytes) -> None:
    rasterizer = PyMuPdfRasterizer()

    with pytest.raises(PdfUnreadable):
        rasterizer.probe(garbage)
    with pytest.raises(PdfUnreadable):
        list(rasterizer.render(garbage, dpi=72))


def test_password_protected_pdf_is_detected() -> None:
    rasterizer = PyMuPdfRasterizer()
    pdf = _encrypted_pdf()

    assert rasterizer.probe(pdf).encrypted is True
    with pytest.raises(PdfEncrypted):
        list(rasterizer.render(pdf, dpi=72))
