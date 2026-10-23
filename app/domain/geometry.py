"""Pixel to PDF-point conversion.

A page rendered at ``dpi`` is ``points * dpi / 72`` pixels wide, so one pixel is
``72 / dpi`` points. Both spaces share the top-left origin with y pointing down,
so the conversion is a pure scale with no flip.
"""

from app.domain.models import Box, OcrWord, PageWord

POINTS_PER_INCH = 72.0


def px_to_pt(value: float, dpi: int) -> float:
    return value * POINTS_PER_INCH / dpi


def box_px_to_pt(box: Box, dpi: int) -> Box:
    return Box(
        x0=px_to_pt(box.x0, dpi),
        y0=px_to_pt(box.y0, dpi),
        x1=px_to_pt(box.x1, dpi),
        y1=px_to_pt(box.y1, dpi),
    )


def word_to_points(word: OcrWord, dpi: int) -> PageWord:
    return PageWord(
        text=word.text,
        box=box_px_to_pt(word.box_px, dpi),
        confidence=word.confidence,
        line_key=word.line_key,
    )
