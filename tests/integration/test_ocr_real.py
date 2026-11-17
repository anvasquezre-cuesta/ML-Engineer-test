"""Real OCR checks: requires Tesseract and the English language data."""

import os
import asyncio
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.core.config import Settings
from app.services.ocr_service import OCRService, PDFPageTooLargeError


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [False, True])
def test_real_ocr_locations_on_scanned_rotated_and_cropped_pages(rotation, crop):
    with pymupdf.open() as original:
        page = original.new_page(width=400, height=300)
        page.insert_text((100, 100), "ALICE SMITH", fontsize=24)
        expected = page.search_for("ALICE")[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        with pymupdf.open() as scanned:
            scanned_page = scanned.new_page(width=400, height=300)
            scanned_page.insert_image(scanned_page.rect, pixmap=pix)
            if crop:
                scanned_page.set_cropbox(pymupdf.Rect(50, 30, 350, 270))
                expected = expected + (-50, -30, -50, -30)
            scanned_page.set_rotation(rotation)
            pdf = scanned.tobytes()

    page = OCRService(Settings(ocr_dpi=200)).extract(pdf).pages[0]
    word = next(word for word in page.words if word.text.upper() == "ALICE")
    center = pymupdf.Point(word.box.x + word.box.width / 2, word.box.y + word.box.height / 2)
    assert center in expected
    assert word.box.width > 0 and word.box.height > 0


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [False, True])
def test_real_ocr_when_metadata_corrects_rotated_scan(rotation, crop):
    with pymupdf.open() as original:
        page = original.new_page(width=400, height=300)
        page.insert_text((100, 100), "ALICE SMITH", fontsize=24)
        expected = page.search_for("ALICE")[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        with Image.frombytes("RGB", (pix.width, pix.height), pix.samples) as image:
            with image.rotate(rotation, expand=True) as rotated:
                buffer = BytesIO()
                rotated.save(buffer, format="PNG")

    x0, y0, x1, y1 = expected
    if rotation == 90:
        expected = pymupdf.Rect(y0, 400 - x1, y1, 400 - x0)
    elif rotation == 180:
        expected = pymupdf.Rect(400 - x1, 300 - y1, 400 - x0, 300 - y0)
    elif rotation == 270:
        expected = pymupdf.Rect(300 - y1, x0, 300 - y0, x1)
    width, height = (300, 400) if rotation in (90, 270) else (400, 300)
    with pymupdf.open() as scanned:
        page = scanned.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=buffer.getvalue())
        if crop:
            page.set_cropbox(pymupdf.Rect(20, 20, width - 20, height - 20))
            expected = expected + (-20, -20, -20, -20)
        page.set_rotation(rotation)
        result = OCRService(Settings(ocr_dpi=200)).extract(scanned.tobytes())

    word = next(word for word in result.pages[0].words if word.text.upper() == "ALICE")
    center = pymupdf.Point(word.box.x + word.box.width / 2, word.box.y + word.box.height / 2)
    assert center in expected


@pytest.mark.parametrize(
    ("filename", "expected_pages"),
    [("company_memo.pdf", 1), ("meeting_minutes.pdf", 2), ("research_report.pdf", 2)],
)
def test_real_ocr_sample_pdfs(filename, expected_pages):
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))
    result = OCRService().extract_file(sample_dir / filename)
    assert len(result.pages) == expected_pages
    for index, page in enumerate(result.pages):
        assert page.page_number == index
        assert page.words
        for word in page.words:
            assert page.text[word.char_start:word.char_end] == word.text
            assert 0 <= word.box.x < page.width
            assert 0 <= word.box.y < page.height
            assert word.box.x + word.box.width <= page.width + 1e-4
            assert word.box.y + word.box.height <= page.height + 1e-4


@pytest.mark.parametrize("input_type", ["bytes", "file", "stream"])
def test_real_ocr_async_processing(input_type):
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))
    service = OCRService()
    pdf_path = sample_dir / "meeting_minutes.pdf"
    class Stream:
        def __init__(self, data):
            self.data = BytesIO(data)

        async def read(self, size=-1):
            return self.data.read(size)

    async def process():
        try:
            if input_type == "bytes":
                return await service.extract_async(pdf_path.read_bytes())
            if input_type == "file":
                return await service.extract_file_async(pdf_path)
            return await service.extract_stream_async(Stream(pdf_path.read_bytes()))
        finally:
            await service.aclose()

    result = asyncio.run(process())
    assert len(result.pages) == 2
    assert all(page.words for page in result.pages)


def test_async_worker_propagates_rendered_pixel_limit():
    with pymupdf.open() as document:
        document.new_page(width=10000, height=10000)
        pdf = document.tobytes()

    async def process():
        service = OCRService()
        try:
            with pytest.raises(PDFPageTooLargeError):
                await service.extract_async(pdf)
        finally:
            await service.aclose()

    asyncio.run(process())
