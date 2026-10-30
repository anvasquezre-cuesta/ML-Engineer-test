"""OCR: render every page of a scanned PDF and return word boxes in PDF points."""

from pathlib import Path
from typing import Protocol

import pymupdf
import pytesseract
from PIL import Image

from app.config import get_settings

Word = dict  # {"word", "page", "x", "y", "width", "height", "line"}, in points


class OcrEngine(Protocol):
    def __call__(self, image: Image.Image) -> dict[str, list]: ...


class InvalidPdfError(ValueError):
    """The bytes are empty, not a PDF, corrupt, or password-protected."""


class DocumentTooLargeError(ValueError):
    """The upload or its page count exceeds the configured limits."""


class OcrEngineError(RuntimeError):
    """Tesseract is missing or failed (timeout included)."""


def tesseract_data(image: Image.Image) -> dict[str, list]:
    """Default engine: Tesseract word table (pixels), configured from settings."""
    settings = get_settings()
    try:
        return pytesseract.image_to_data(
            image,
            lang=settings.ocr_lang,
            config=f"--psm {settings.ocr_psm}",
            timeout=settings.ocr_timeout_s,
            output_type=pytesseract.Output.DICT,
        )
    except (RuntimeError, pytesseract.TesseractNotFoundError) as err:
        raise OcrEngineError("Tesseract failed or is not installed") from err


def _page_words(page: pymupdf.Page, engine: OcrEngine) -> list[Word]:
    """OCR one page; drop conf < 0 and blank text; pixels -> points."""
    settings = get_settings()
    pix = page.get_pixmap(dpi=settings.ocr_dpi, colorspace=pymupdf.csGRAY)
    scale = page.rect.width / pix.width
    data = engine(pix.pil_image())
    cols = "text conf left top width height block_num par_num line_num".split()
    rows = zip(*(data[c] for c in cols), strict=True)
    words = []
    for text, conf, left, top, width, height, block, par, line_num in rows:
        if float(conf) < 0 or not text.strip():
            continue
        x, y, w, h = (v * scale for v in (left, top, width, height))
        if settings.bbox_origin == "bottom-left":
            y = page.rect.height - y - h
        box = {"x": x, "y": y, "width": w, "height": h}
        line = (block, par, line_num)
        words.append({"word": text.strip(), "page": page.number, **box, "line": line})
    return words


def ocr_pages(pdf_bytes: bytes, engine: OcrEngine | None = None) -> list[list[Word]]:
    """OCR every page (including the first); one list of words per page."""
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            if not doc.is_pdf:  # pymupdf opens images (PNG...) despite filetype
                raise InvalidPdfError("not a PDF")
            if doc.needs_pass:
                raise InvalidPdfError("password-protected PDF")
            if doc.page_count > get_settings().max_pages:
                raise DocumentTooLargeError("too many pages")
            return [_page_words(page, engine or tesseract_data) for page in doc]
    except pymupdf.FileDataError as err:
        raise InvalidPdfError("not a readable PDF") from err


def page_text(words: list[Word]) -> tuple[str, list[Word]]:
    """Page text and copies of the words with their start/end offsets in it."""
    text, placed, prev_line = "", [], None
    for word in words:
        if prev_line is not None:
            text += " " if word["line"] == prev_line else "\n"
        placed.append(
            {**word, "start": len(text), "end": len(text) + len(word["word"])}
        )
        text += word["word"]
        prev_line = word["line"]
    return text, placed


def extract_text_from_pdf(pdf_path: str) -> str:
    """Return the OCR'd text of the whole document (pages joined by a blank line)."""
    pages = ocr_pages(Path(pdf_path).read_bytes())
    return "\n\n".join(page_text(words)[0] for words in pages)


def get_word_bounding_boxes(pdf_path: str) -> list[dict]:
    """Return one dict per recognized word, in page order, in PDF points."""
    return [w for words in ocr_pages(Path(pdf_path).read_bytes()) for w in words]
