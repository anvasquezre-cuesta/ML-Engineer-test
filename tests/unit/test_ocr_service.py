from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from app.core.config import Settings
from app.services.ocr_service import (
    InvalidPDFError,
    OCRProcessingError,
    OCRService,
    PDFPageTooLargeError,
    PDFTooLargeError,
)


def make_pdf(pages=1, rotation=0, crop=False):
    with pymupdf.open() as document:
        for _ in range(pages):
            page = document.new_page(width=400, height=300)
            if crop:
                page.set_cropbox(pymupdf.Rect(50, 30, 350, 270))
            page.set_rotation(rotation)
        return document.tobytes()


def ocr_data(words):
    columns = ("text", "left", "top", "width", "height", "block_num", "par_num", "line_num", "conf")
    return {key: [word[index] for word in words] for index, key in enumerate(columns)}


def test_extracts_every_page_and_tracks_page_text_offsets(monkeypatch):
    calls = []

    def fake_ocr(image, **kwargs):
        calls.append(kwargs)
        return ocr_data([
            (" Alice ", 20, 40, 60, 20, 1, 1, 1, 94),
            ("Smith", 90, 40, 50, 20, 1, 1, 1, 92),
            ("Next", 20, 80, 40, 20, 1, 1, 2, 88),
            ("  ", 0, 0, 0, 0, 0, 0, 0, -1),
        ])

    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", fake_ocr)
    result = OCRService(Settings(ocr_dpi=144, ocr_languages="eng", ocr_timeout_seconds=12)).extract(make_pdf(pages=2))

    assert len(calls) == 2
    assert all(call["lang"] == "eng" and call["timeout"] == 12 for call in calls)
    assert [page.page_number for page in result.pages] == [0, 1]
    assert result.text == "Alice Smith\nNext\n\nAlice Smith\nNext"
    for page in result.pages:
        assert page.width == 400 and page.height == 300
        assert all(page.text[word.char_start:word.char_end] == word.text for word in page.words)
        assert page.words[0].box.x == pytest.approx(10)
        assert page.words[0].box.y == pytest.approx(20)
        assert page.words[0].box.width == pytest.approx(30)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [False, True])
def test_coordinate_transform_with_rotation_and_crop(monkeypatch, rotation, crop):
    pdf = make_pdf(rotation=rotation, crop=crop)
    expected = pymupdf.Rect(20, 30, 60, 45)
    scale = 2
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        page = document[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        rendered = expected * page.rotation_matrix * pymupdf.Matrix(scale, scale)
        x0, y0, x1, y1 = rendered.x0 - pix.x, rendered.y0 - pix.y, rendered.x1 - pix.x, rendered.y1 - pix.y
        if rotation == 90:
            x0, y0, x1, y1 = y0, pix.width - x1, y1, pix.width - x0
        elif rotation == 180:
            x0, y0, x1, y1 = pix.width - x1, pix.height - y1, pix.width - x0, pix.height - y0
        elif rotation == 270:
            x0, y0, x1, y1 = pix.height - y1, x0, pix.height - y0, x1
        row = ("Name", x0, y0, x1 - x0, y1 - y0, 1, 1, 1, 95)

    calls = 0

    def fake_ocr(*args, **kwargs):
        nonlocal calls
        calls += 1
        if rotation and calls == 1:
            return ocr_data([("uncertain", 1, 1, 10, 10, 1, 1, 1, 1)])
        return ocr_data([row])

    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", fake_ocr)
    result = OCRService(Settings(ocr_dpi=144)).extract(pdf)
    box = result.pages[0].words[0].box
    assert (box.x, box.y, box.width, box.height) == pytest.approx((20, 30, 40, 15))
    assert (result.pages[0].width, result.pages[0].height) == ((300, 240) if crop else (400, 300))


def test_clips_and_skips_invalid_boxes(monkeypatch):
    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", lambda *a, **kw: ocr_data([
        ("partial", -10, 0, 30, 10, 1, 1, 1, 90),
        ("outside", 1000, 0, 10, 10, 1, 1, 1, 90),
        ("empty", 0, 0, 0, 10, 1, 1, 1, 90),
    ]))
    page = OCRService(Settings(ocr_dpi=72)).extract(make_pdf()).pages[0]
    assert page.text == "partial"
    assert page.words[0].box.x == 0
    assert page.words[0].box.width == 20


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.4\nnot a real document"])
def test_rejects_empty_invalid_or_corrupt_pdf(data):
    with pytest.raises(InvalidPDFError):
        OCRService().extract(data)


def test_rejects_oversized_pdf():
    with pytest.raises(PDFTooLargeError):
        OCRService(Settings(max_upload_bytes=4)).extract(b"12345")


def test_rejects_image_even_with_pdf_input_type():
    data = BytesIO()
    with Image.new("RGB", (10, 10)) as image:
        image.save(data, format="PNG")
    with pytest.raises(InvalidPDFError):
        OCRService().extract(data.getvalue())


def test_extract_file_rejects_oversized_file(tmp_path):
    path = tmp_path / "too-large.pdf"
    path.write_bytes(b"12345")
    with pytest.raises(PDFTooLargeError):
        OCRService(Settings(max_upload_bytes=4)).extract_file(path)


def test_rejects_too_many_pages():
    with pytest.raises(InvalidPDFError, match="page limit"):
        OCRService(Settings(max_pdf_pages=1)).extract(make_pdf(pages=2))


def test_large_page_rejected_before_rendering(monkeypatch):
    with pymupdf.open() as document:
        document.new_page(width=10000, height=10000)
        pdf = document.tobytes()

    def unexpected_render(*args, **kwargs):
        raise AssertionError("large page must be rejected before rendering")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", unexpected_render)
    with pytest.raises(PDFPageTooLargeError, match="pixel"):
        OCRService().extract(pdf)


def test_rendered_pixel_limit_accounts_for_dpi(monkeypatch):
    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", lambda *a, **kw: ocr_data([]))
    pdf = make_pdf()
    assert OCRService(Settings(ocr_dpi=72, max_page_pixels=121_000)).extract(pdf).pages
    with pytest.raises(PDFPageTooLargeError):
        OCRService(Settings(ocr_dpi=144, max_page_pixels=121_000)).extract(pdf)


def test_rejects_password_protected_pdf():
    with pymupdf.open() as document:
        document.new_page()
        pdf = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-password",
            user_pw="user-password",
        )
    with pytest.raises(InvalidPDFError, match="unencrypted"):
        OCRService().extract(pdf)


def test_wraps_ocr_failures_and_closes_images(monkeypatch):
    observed = []
    documents = []
    pdf = make_pdf()
    real_open = pymupdf.open

    def open_document(*args, **kwargs):
        document = real_open(*args, **kwargs)
        documents.append(document)
        return document

    def fail(image, **kwargs):
        observed.append(image)
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr("app.services.ocr_service.pytesseract.image_to_data", fail)
    monkeypatch.setattr("app.services.ocr_service.pymupdf.open", open_document)
    with pytest.raises(OCRProcessingError, match="page 0"):
        OCRService().extract(pdf)
    with pytest.raises(ValueError, match="closed"):
        observed[0].getpixel((0, 0))
    assert documents[0].is_closed
