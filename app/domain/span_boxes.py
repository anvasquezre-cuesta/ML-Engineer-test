"""Locates PERSON spans on the page through the words they overlap."""

from app.domain.extraction import EntitySpan
from app.domain.extraction import NameOccurrence
from app.domain.extraction import PageText


def locate_span(  # noqa: DOC501, DOC503
    page: PageText, span: EntitySpan
) -> list[NameOccurrence]:
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
    raise NotImplementedError
