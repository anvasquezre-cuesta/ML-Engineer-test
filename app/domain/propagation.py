"""Recovers repeats of accepted names that NER did not tag."""

from collections.abc import Collection
from collections.abc import Sequence

from app.domain import extraction
from app.domain import normalize

MIN_TOKENS = 2


def _trimmed_span(
    page: extraction.PageText,
    first: extraction.TextWord,
    last: extraction.TextWord,
) -> extraction.EntitySpan:
    """Returns the span from ``first`` to ``last`` without edge punctuation.

    Args:
        page: The page holding both words.
        first: First word of the match.
        last: Last word of the match.

    Returns:
        The span of the matched name.
    """
    lead = len(first.word.text) - len(
        first.word.text.lstrip(normalize.EDGE_PUNCTUATION)
    )
    tail = len(last.word.text) - len(
        last.word.text.rstrip(normalize.EDGE_PUNCTUATION)
    )
    start, end = first.start + lead, last.end - tail
    return extraction.EntitySpan(
        start=start, end=end, text=page.text[start:end]
    )


def _overlaps(a: extraction.EntitySpan, b: extraction.EntitySpan) -> bool:
    """Returns whether two spans share at least one character.

    Args:
        a: A span.
        b: Another span of the same text.

    Returns:
        ``True`` if the spans overlap.
    """
    return a.start < b.end and b.start < a.end


def propagate(
    page: extraction.PageText,
    names: Collection[str],
    spans: Sequence[extraction.EntitySpan],
) -> list[extraction.EntitySpan]:
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
    tokenized = {
        tuple(normalize.normalize_name(name).split()) for name in names
    }
    # Longest first, so a longer name wins over a shorter one it contains.
    targets = sorted(
        (target for target in tokenized if len(target) >= MIN_TOKENS),
        key=len,
        reverse=True,
    )
    keys = [normalize.normalize_name(w.word.text) for w in page.words]
    taken = list(spans)
    found: list[extraction.EntitySpan] = []
    for index in range(len(page.words)):
        for target in targets:
            if tuple(keys[index : index + len(target)]) != target:
                continue
            span = _trimmed_span(
                page, page.words[index], page.words[index + len(target) - 1]
            )
            if any(_overlaps(span, other) for other in taken):
                continue
            found.append(span)
            taken.append(span)
    return found
