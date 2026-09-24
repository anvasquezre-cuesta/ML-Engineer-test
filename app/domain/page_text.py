"""Builds the text of a page from its OCR words."""

from app.domain import extraction


def _separator(previous: extraction.OcrWord, word: extraction.OcrWord) -> str:
    r"""Returns the text placed between two consecutive words.

    Args:
        previous: The earlier word.
        word: The word that follows it.

    Returns:
        ``\n\n`` across blocks, ``\n`` across lines, else a space.
    """
    if word.block != previous.block:
        return "\n\n"
    if word.line != previous.line:
        return "\n"
    return " "


def build_page_text(page: extraction.PageWords) -> extraction.PageText:
    """Joins the words of ``page`` into text, recording each word's offsets.

    Args:
        page: The words of one page in reading order.

    Returns:
        The page text with every word located in it.
    """
    parts: list[str] = []
    located: list[extraction.TextWord] = []
    offset = 0
    previous: extraction.OcrWord | None = None
    for word in page.words:
        if previous is not None:
            separator = _separator(previous, word)
            parts.append(separator)
            offset += len(separator)
        located.append(
            extraction.TextWord(
                word=word, start=offset, end=offset + len(word.text)
            )
        )
        parts.append(word.text)
        offset += len(word.text)
        previous = word
    return extraction.PageText(
        page_number=page.page_number,
        text="".join(parts),
        words=tuple(located),
    )
