"""Find person names in OCR output and locate each one on its page.

spaCy reports entities as character ranges of a string; boxes belong to OCR
words. The bridge is an offset map: each line's text is built from its words
while recording which characters each word occupies, and an entity's box is the
union of the words its range overlaps.

NER runs per OCR line. On whole-page text spaCy merged entities across
newlines (a heading plus the next line tagged as one person), and per-line
input makes an entity spanning two lines impossible by construction. The cost:
a name wrapped onto the next line would be split.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import fmean

import structlog

from app.domain.models import Box, EntitySpan, OcrPage, PageWord, PersonMention
from app.domain.protocols import NERModel

logger = structlog.get_logger(__name__)

# Entity edges are trimmed so the name and its box cover only what a reviewer verifies:
# list bullets and brackets before it, an honorific, and punctuation after it.
_LEADING_NOISE = re.compile(r"^[\W\d_]+")  # anything that is not a letter
_LEADING_TITLE = re.compile(r"^(?:dr|prof|mr|mrs|ms|mx|sir|dame)\.?\s+", re.IGNORECASE)
_TRAILING_NOISE = re.compile(
    r"[\s,;:()\[\]\"'\N{RIGHT SINGLE QUOTATION MARK}\N{EN DASH}\N{EM DASH}-]+$"
)


@dataclass(frozen=True, slots=True)
class Line:
    page: int
    words: tuple[PageWord, ...]
    text: str
    spans: tuple[tuple[int, int], ...]  # character range of each word in ``text``


def group_lines(page: OcrPage) -> list[Line]:
    """Group a page's words by Tesseract line, keeping reading order."""
    grouped: dict[tuple[int, int, int], list[PageWord]] = {}
    for word in page.words:
        grouped.setdefault(word.line_key, []).append(word)
    return [build_line(page.index, words) for words in grouped.values()]


def build_line(page: int, words: Sequence[PageWord]) -> Line:
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    position = 0
    for i, word in enumerate(words):
        if i:
            parts.append(" ")
            position += 1
        spans.append((position, position + len(word.text)))
        parts.append(word.text)
        position += len(word.text)
    return Line(page=page, words=tuple(words), text="".join(parts), spans=tuple(spans))


def words_in_span(line: Line, start: int, end: int) -> list[PageWord]:
    """Words whose characters overlap ``[start, end)``.

    Overlap, not exact match: spaCy may split one OCR word into several tokens
    (``Al-Rashidi``), and entity edges rarely align with OCR words that carry
    punctuation (``Foster):``).
    """
    return [w for w, (a, b) in zip(line.words, line.spans, strict=True) if a < end and b > start]


def union_box(boxes: Sequence[Box]) -> Box:
    return Box(
        x0=min(b.x0 for b in boxes),
        y0=min(b.y0 for b in boxes),
        x1=max(b.x1 for b in boxes),
        y1=max(b.y1 for b in boxes),
    )


def clean_entity(entity: EntitySpan) -> EntitySpan:
    """Trim bullets, titles and punctuation, moving the character range with the text.

    spaCy sometimes includes a list bullet (``- Jennifer Liu``); trimming the text
    alone would leave the bullet's word inside the box.
    """
    text, start, end = entity.text, entity.start_char, entity.end_char
    for leading in (_LEADING_NOISE, _LEADING_TITLE, _LEADING_NOISE):
        if match := leading.match(text):
            text, start = text[match.end() :], start + match.end()
    if match := _TRAILING_NOISE.search(text):
        end -= len(text) - match.start()
        text = text[: match.start()]
    if (text, start, end) == (entity.text, entity.start_char, entity.end_char):
        return entity
    return EntitySpan(text=text, start_char=start, end_char=end)


# Rejection filters: each returns True when a candidate is NOT a usable person name.
# Named functions so each one can be tested, explained and switched off on its own.


def is_all_caps(name: str) -> bool:
    """Headings such as ``RESEARCH DEPARTMENT``. Cost: drops an all-caps signature name."""
    letters = [c for c in name if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def has_fewer_than_two_tokens(name: str) -> bool:
    """Single words such as ``Atlas`` or ``Forbes``. Cost: drops a lone surname."""
    return len(name.split()) < 2


NameFilter = Callable[[str], bool]
DEFAULT_FILTERS: tuple[NameFilter, ...] = (is_all_caps, has_fewer_than_two_tokens)


class NameExtractor:
    def __init__(self, ner: NERModel, filters: Sequence[NameFilter] = DEFAULT_FILTERS) -> None:
        self._ner = ner
        self._filters = tuple(filters)

    def extract(self, pages: Sequence[OcrPage]) -> list[PersonMention]:
        started = time.perf_counter()
        lines = [line for page in pages for line in group_lines(page)]
        entities_per_line = self._ner.find_persons([line.text for line in lines])

        mentions: list[PersonMention] = []
        rejected = 0
        for line, entities in zip(lines, entities_per_line, strict=True):
            for entity in map(clean_entity, entities):
                mention = self._locate(line, entity)
                if mention is None or any(reject(mention.name) for reject in self._filters):
                    rejected += 1
                    continue
                mentions.append(mention)

        logger.info(
            "names_extracted",
            page_count=len(pages),
            line_count=len(lines),
            names_found=len(mentions),
            candidates_rejected=rejected,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return mentions

    @staticmethod
    def _locate(line: Line, entity: EntitySpan) -> PersonMention | None:
        words = words_in_span(line, entity.start_char, entity.end_char)
        if not words:
            return None
        return PersonMention(
            name=entity.text,
            page=line.page,
            box=union_box([w.box for w in words]),
            confidence=fmean(w.confidence for w in words),
        )
