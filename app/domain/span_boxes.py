"""Locates PERSON spans on the page through the words they overlap."""

from collections.abc import Iterable
import itertools

from app.domain import extraction
from app.domain import normalize

TITLES = frozenset({"dr", "prof", "mr", "mrs", "ms", "mx", "sir", "dame"})


def _union(boxes: Iterable[extraction.Box]) -> extraction.Box:
    """Returns the smallest box containing every box.

    Args:
        boxes: At least one box.

    Returns:
        Their bounding box.
    """
    edges = [(b.x, b.y, b.x + b.width, b.y + b.height) for b in boxes]
    x0 = min(edge[0] for edge in edges)
    y0 = min(edge[1] for edge in edges)
    x1 = max(edge[2] for edge in edges)
    y1 = max(edge[3] for edge in edges)
    return extraction.Box(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def locate_span(
    page: extraction.PageText, span: extraction.EntitySpan
) -> list[extraction.NameOccurrence]:
    """Returns the boxes of ``span`` on ``page``, one per line it covers.

    Leading titles such as ``Dr.`` or ``Prof.`` are left out of the name and
    the box. The box of each line segment is the union of the words the span
    overlaps on that line, so two names on one line stay separate. A span
    whose words fall in more than one text block is dropped.

    Args:
        page: The page text the span was found in.
        span: A PERSON span, as offsets into ``page.text``.

    Returns:
        One occurrence per line segment, or none if the span is dropped or
        holds only a title.
    """
    words = [w for w in page.words if w.start < span.end and w.end > span.start]
    while words and normalize.normalize_name(words[0].word.text) in TITLES:
        words.pop(0)
    if not words or len({w.word.block for w in words}) > 1:
        return []
    start = max(span.start, words[0].start)
    name = " ".join(page.text[start : span.end].split())
    lines: Iterable[tuple[int, Iterable[extraction.TextWord]]] = (
        itertools.groupby(words, key=lambda w: w.word.line)
    )
    return [
        extraction.NameOccurrence(
            name=name,
            page_number=page.page_number,
            box=_union(w.word.box for w in line_words),
        )
        for _, line_words in lines
    ]
