"""Hand-written fakes for the domain Protocols.

Each is a tiny working implementation, so tests read like the domain and the
same fake serves many tests. They also record calls for assertions.
"""

from collections.abc import Iterator

from app.domain.models import Box, OcrWord, PageImage


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
