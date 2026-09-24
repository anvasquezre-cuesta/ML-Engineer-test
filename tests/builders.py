"""Builders for extraction test data with predictable geometry."""

from collections.abc import Sequence

from app.domain import extraction

CHAR_WIDTH = 6.0
LINE_HEIGHT = 12.0
LINE_PITCH = 20.0
BLOCK_GAP = 40.0
MARGIN = 72.0


def page_words(
    blocks: Sequence[Sequence[str]], page_number: int = 0
) -> extraction.PageWords:
    """Lays out words left to right, lines top to bottom, blocks apart.

    Args:
        blocks: Each block is a sequence of lines; a line's words are split
            on whitespace.
        page_number: 0-based page index.

    Returns:
        The words in reading order.
    """
    words = []
    y = MARGIN
    for block_index, block in enumerate(blocks):
        for line_index, line in enumerate(block):
            x = MARGIN
            for token in line.split():
                width = CHAR_WIDTH * len(token)
                box = extraction.Box(x=x, y=y, width=width, height=LINE_HEIGHT)
                words.append(
                    extraction.OcrWord(
                        text=token,
                        box=box,
                        block=block_index,
                        line=line_index,
                        confidence=95.0,
                    )
                )
                x += width + CHAR_WIDTH
            y += LINE_PITCH
        y += BLOCK_GAP
    return extraction.PageWords(page_number=page_number, words=tuple(words))


def box_of(
    page: extraction.PageWords, text: str, nth: int = 0
) -> extraction.Box:
    """Returns the box of the ``nth`` word whose text is ``text``.

    Args:
        page: The laid-out page.
        text: Exact word text.
        nth: 0-based occurrence index.

    Returns:
        The word's box.
    """
    return [word.box for word in page.words if word.text == text][nth]


def union(*boxes: extraction.Box) -> extraction.Box:
    """Returns the smallest box containing every box.

    Args:
        *boxes: Boxes to cover.

    Returns:
        Their bounding box.
    """
    x0 = min(box.x for box in boxes)
    y0 = min(box.y for box in boxes)
    x1 = max(box.x + box.width for box in boxes)
    y1 = max(box.y + box.height for box in boxes)
    return extraction.Box(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def span_of(text: str, needle: str, nth: int = 0) -> extraction.EntitySpan:
    """Returns the span of the ``nth`` occurrence of ``needle`` in ``text``.

    Args:
        text: The source text.
        needle: Exact substring to locate.
        nth: 0-based occurrence index.

    Returns:
        The span, as NER would report it.
    """
    start = -1
    for _ in range(nth + 1):
        start = text.index(needle, start + 1)
    return extraction.EntitySpan(
        start=start, end=start + len(needle), text=needle
    )
