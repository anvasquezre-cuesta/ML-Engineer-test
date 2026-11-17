"""Locate page-local NER spans using the OCR words from the same pass."""

from bisect import bisect_left, bisect_right
import math

from app.models.document import OCRPage, OCRWord
from app.models.extraction import PersonSpan
from app.models.schemas import BoundingBox, ExtractedName


def _valid_word(page: OCRPage, word: OCRWord) -> bool:
    box = word.box
    values = (box.x, box.y, box.width, box.height, page.width, page.height)
    return (
        all(math.isfinite(value) for value in values)
        and 0 <= word.char_start < word.char_end <= len(page.text)
        and page.text[word.char_start:word.char_end] == word.text
        and box.x >= 0 and box.y >= 0 and box.width > 0 and box.height > 0
        and box.x + box.width <= page.width + 1e-4
        and box.y + box.height <= page.height + 1e-4
    )


def _adjacent(first: OCRWord, second: OCRWord) -> bool:
    if (first.block_number, first.paragraph_number) != (second.block_number, second.paragraph_number):
        return False
    height = max(first.box.height, second.box.height)
    if first.line_number == second.line_number:
        gap = second.box.x - (first.box.x + first.box.width)
        return -height <= gap <= 4 * height and abs(first.box.y - second.box.y) <= height
    if second.line_number != first.line_number + 1:
        return False
    vertical_gap = second.box.y - (first.box.y + first.box.height)
    return -height <= vertical_gap <= 3 * height


class PageLocator:
    """Index one page once so repeated entities do not rescan every OCR word."""

    def __init__(self, page: OCRPage):
        self.page = page
        self.starts = [word.char_start for word in page.words]
        self.ends = [word.char_end for word in page.words]
        self.valid = all(_valid_word(page, word) for word in page.words) and all(
            previous.char_end <= current.char_start for previous, current in zip(page.words, page.words[1:])
        )

    def locate(self, span: PersonSpan) -> ExtractedName | None:
        return _locate(self, span)


def locate_person_span(page: OCRPage, span: PersonSpan) -> ExtractedName | None:
    """Return a conservative enclosing box, or None if association is unsafe.

    Offsets refer to this page's reconstructed OCR text. Whitespace between
    words is allowed; non-whitespace gaps, unrelated blocks and distant words
    are not. A partial-word entity still uses that OCR word's whole rectangle.
    """
    return PageLocator(page).locate(span)


def _locate(locator: PageLocator, span: PersonSpan) -> ExtractedName | None:
    page = locator.page
    if not locator.valid or span.char_end > len(page.text) or page.text[span.char_start:span.char_end] != span.text:
        return None
    start = bisect_right(locator.ends, span.char_start)
    end = bisect_left(locator.starts, span.char_end)
    selected = page.words[start:end]
    if not selected:
        return None
    if any(not _adjacent(left, right) for left, right in zip(selected, selected[1:])):
        return None

    cursor = span.char_start
    for word in selected:
        start = max(word.char_start, span.char_start)
        if start < cursor or page.text[cursor:start].strip():
            return None
        cursor = min(word.char_end, span.char_end)
    if page.text[cursor:span.char_end].strip():
        return None

    words = selected
    left = min(word.box.x for word in words)
    top = min(word.box.y for word in words)
    right = max(word.box.x + word.box.width for word in words)
    bottom = max(word.box.y + word.box.height for word in words)
    return ExtractedName(name=span.text, bounding_box=BoundingBox(
        page_number=page.page_number, x=left, y=top, width=right - left, height=bottom - top,
    ))


def find_name_bounding_boxes(pdf_path: str, text: str) -> list[dict]:
    """Locate a supplied name in a PDF for legacy synchronous callers.

    This compatibility helper runs its own OCR. The HTTP extraction pipeline
    uses page-local spans and never calls it, so it does not repeat OCR.
    """
    from thefuzz import fuzz

    from app.core.config import get_settings
    from app.services.fuzzy_service import normalize_name
    from app.services.ocr_service import OCRService

    target = normalize_name(text)
    if not target:
        return []
    settings = get_settings()
    token_count = len(target.split())
    results = []
    for page in OCRService(settings).extract_file(pdf_path).pages:
        locator = PageLocator(page)
        seen = set()
        for start in range(len(page.words)):
            for count in range(max(1, token_count - 1), token_count + 2):
                end = start + count
                if end > len(page.words):
                    break
                first, last = page.words[start], page.words[end - 1]
                candidate = page.text[first.char_start:last.char_end]
                if not candidate.strip() or fuzz.ratio(target, normalize_name(candidate)) / 100 < settings.fuzzy_threshold:
                    continue
                location = locator.locate(PersonSpan(candidate, first.char_start, last.char_end))
                if location is None or (first.char_start, last.char_end) in seen:
                    continue
                seen.add((first.char_start, last.char_end))
                box = location.bounding_box
                results.append({"name": location.name, "page": box.page_number, "x": box.x, "y": box.y,
                                "width": box.width, "height": box.height})
    return results
