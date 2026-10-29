"""Map NER character spans to OCR word boxes: one box per real occurrence (TRD ADR-004).

No string search: a span selects exactly the words whose offsets it overlaps, so repeated
names and unrelated look-alike words can't be confused.
"""

import logging
from collections.abc import Sequence

from app.domain.document import LineKey, Page, Word
from app.domain.geometry import union_box
from app.domain.page_text import PageText
from app.domain.persons import NameOccurrence, PersonSpan

logger = logging.getLogger(__name__)


def locate_occurrences(
    page: Page, page_text: PageText, spans: Sequence[PersonSpan]
) -> list[NameOccurrence]:
    """One occurrence per span and line it covers, in page-text (reading) order."""
    located: list[tuple[int, NameOccurrence]] = []
    for span in spans:
        indexes = [
            i
            for i, (start, end) in enumerate(page_text.word_spans)
            if start < span.end and end > span.start
        ]
        if not indexes:
            logger.warning(
                "alignment_span_unmatched",
                extra={"page_index": page.index, "start": span.start, "end": span.end},
            )
            continue
        name = " ".join(span.text.split())  # a name wrapped across lines reads as one line
        for first_index, words in _group_by_line(page.words, indexes):
            box = union_box([word.box for word in words])
            located.append(
                (page_text.word_spans[first_index][0], NameOccurrence(name, page.index, box))
            )
    located.sort(key=lambda item: item[0])
    return [occurrence for _, occurrence in located]


def _group_by_line(words: Sequence[Word], indexes: list[int]) -> list[tuple[int, list[Word]]]:
    """Split selected word indexes into per-line groups, keeping their order."""
    groups: dict[LineKey, tuple[int, list[Word]]] = {}
    for i in indexes:
        groups.setdefault(words[i].line_key, (i, []))[1].append(words[i])
    return list(groups.values())
