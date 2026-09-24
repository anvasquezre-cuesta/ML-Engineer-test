"""Recovers repeats of accepted names that NER did not tag."""

from collections.abc import Collection
from collections.abc import Sequence

from app.domain.extraction import EntitySpan
from app.domain.extraction import PageText


def propagate(  # noqa: DOC501, DOC503
    page: PageText, names: Collection[str], spans: Sequence[EntitySpan]
) -> list[EntitySpan]:
    """Finds untagged occurrences of ``names`` on ``page``.

    Only names of at least two tokens are searched, as the exact sequence of
    their normalized tokens over consecutive words. Punctuation around the
    matched words is left out of the new span. Matches that overlap an
    existing span are skipped.

    Args:
        page: The page to search.
        names: Names accepted anywhere in the document, without titles.
        spans: The spans already found on ``page``.

    Returns:
        The new spans, in page order.
    """
    raise NotImplementedError
