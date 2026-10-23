"""Hand-written fakes for the domain Protocols.

Each is a tiny working implementation, so tests read like the domain and the
same fake serves many tests. They also record calls for assertions.
"""

from collections.abc import Iterator, Sequence

from app.domain.models import Box, EntitySpan, OcrPage, OcrWord, PageImage, PageWord


def blank_page(index: int, *, dpi: int = 72, rotation: int = 0) -> PageImage:
    """A US Letter page; at the default 72 DPI one pixel is one point."""
    width_px, height_px = round(612 * dpi / 72), round(792 * dpi / 72)
    return PageImage(
        index=index,
        width_pt=612.0,
        height_pt=792.0,
        rotation=rotation,
        dpi=dpi,
        width_px=width_px,
        height_px=height_px,
        pixels=b"",  # fakes never read the pixels
    )


class FakeRenderer:
    def __init__(self, pages: list[PageImage]) -> None:
        self.pages = pages
        self.page_count_calls = 0

    def page_count(self, pdf: bytes) -> int:
        self.page_count_calls += 1
        return len(self.pages)

    def render(self, pdf: bytes, dpi: int) -> Iterator[PageImage]:
        yield from self.pages


class FakeOCR:
    """Returns ``words_by_page[index]`` for each page and records which pages it saw."""

    def __init__(self, words_by_page: dict[int, list[OcrWord]] | None = None) -> None:
        self.words_by_page = words_by_page or {}
        self.seen_pages: list[int] = []

    def recognize(self, page: PageImage) -> list[OcrWord]:
        self.seen_pages.append(page.index)
        return self.words_by_page.get(page.index, [])


def ocr_word(
    text: str, x0: float, y0: float, x1: float, y1: float, line: int = 1, conf: float = 95.0
) -> OcrWord:
    return OcrWord(text=text, box_px=Box(x0, y0, x1, y1), confidence=conf, line_key=(1, 1, line))


CHAR_WIDTH_PT = 5.0
LINE_HEIGHT_PT = 10.0


def words_on_line(
    text: str, line: int, *, x: float = 50.0, conf: float | Sequence[float] = 95.0
) -> list[PageWord]:
    """Lay out ``text`` word by word on one line: 5 pt per character, one space between words."""
    y0 = 100.0 + line * 2 * LINE_HEIGHT_PT
    tokens = text.split()
    confidences = [conf] * len(tokens) if isinstance(conf, float | int) else list(conf)
    words = []
    for token, confidence in zip(tokens, confidences, strict=True):
        x1 = x + len(token) * CHAR_WIDTH_PT
        words.append(
            PageWord(
                text=token,
                box=Box(x, y0, x1, y0 + LINE_HEIGHT_PT),
                confidence=confidence,
                line_key=(1, 1, line),
            )
        )
        x = x1 + CHAR_WIDTH_PT
    return words


def ocr_page(index: int, *lines: list[PageWord]) -> OcrPage:
    return OcrPage(
        index=index,
        width_pt=612.0,
        height_pt=792.0,
        words=tuple(word for line in lines for word in line),
    )


class FakeNER:
    """Tags every occurrence of the given strings as a person and records its calls."""

    def __init__(self, *persons: str) -> None:
        self.persons = persons
        self.calls: list[list[str]] = []

    def find_persons(self, texts: Sequence[str]) -> list[list[EntitySpan]]:
        self.calls.append(list(texts))
        return [self._find(text) for text in texts]

    def _find(self, text: str) -> list[EntitySpan]:
        spans = []
        for person in self.persons:
            start = text.find(person)
            while start != -1:
                spans.append(EntitySpan(person, start, start + len(person)))
                start = text.find(person, start + 1)
        return sorted(spans, key=lambda s: s.start_char)
