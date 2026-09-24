"""Builds the text of a page from its OCR words."""

from app.domain.extraction import PageText
from app.domain.extraction import PageWords


def build_page_text(page: PageWords) -> PageText:  # noqa: DOC501, DOC503
    """Joins the words of ``page`` into text, recording each word's offsets.

    Args:
        page: The words of one page in reading order.

    Returns:
        The page text with every word located in it.
    """
    raise NotImplementedError
