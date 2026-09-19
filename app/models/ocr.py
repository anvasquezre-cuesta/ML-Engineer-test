"""
Module: app.models.ocr
Path: app/models/ocr.py
Description: Internal data models used to represent OCR results.
"""


class OCRWord:
    """Represent one OCR-recognized word and its position on a page."""

    def __init__(
        self,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class OCRPage:
    """Represent the OCR result for one page of a PDF document."""

    def __init__(
        self,
        page_number: int,
        text: str,
        words: list[OCRWord],
    ) -> None:
        self.page_number = page_number
        self.text = text
        self.words = words


class OCRDocument:
    """Represent the complete OCR result for a PDF document."""

    def __init__(self, pages: list[OCRPage]) -> None:
        self.pages = pages
