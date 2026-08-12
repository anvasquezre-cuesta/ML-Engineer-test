"""OCR: turn a scanned PDF into text and per-word bounding boxes.

Implement this. The sample PDFs in ``sample_pdfs/`` are scanned images — there
is no selectable text layer, so you must render each page and run OCR.

Reminders (these are graded):
- Process EVERY page, including the first.
- Return word boxes in PDF coordinate space (points, 72/inch), not image pixels.
- Do not leak file handles or temp files.
"""


def extract_text_from_pdf(pdf_path: str) -> str:
    """Return the OCR'd text of the whole document."""
    raise NotImplementedError


def get_word_bounding_boxes(pdf_path: str) -> list[dict]:
    """Return one dict per recognized word.

    Suggested shape (you may adapt): ``{"word", "page", "x", "y", "width",
    "height"}`` with coordinates in PDF points and a 0-based ``page``.
    """
    raise NotImplementedError
