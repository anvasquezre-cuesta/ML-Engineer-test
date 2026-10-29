"""Page text with per-word character offsets (TRD ADR-004).

The single source of offsets: the recognizer reads ``text`` and alignment maps its spans
back to words through ``word_spans``.
"""

from dataclasses import dataclass

from app.domain.document import Page

WORD_SEPARATOR = " "
LINE_SEPARATOR = "\n"


@dataclass(frozen=True, slots=True)
class PageText:
    """A page's text; ``word_spans[i]`` is the ``[start, end)`` of ``page.words[i]``."""

    text: str
    word_spans: tuple[tuple[int, int], ...]


def build_page_text(page: Page) -> PageText:
    """Join words with a space within a line and a newline between lines."""
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    previous_line = None
    for word in page.words:
        if previous_line is not None:
            separator = WORD_SEPARATOR if word.line_key == previous_line else LINE_SEPARATOR
            parts.append(separator)
            cursor += len(separator)
        parts.append(word.text)
        spans.append((cursor, cursor + len(word.text)))
        cursor += len(word.text)
        previous_line = word.line_key
    return PageText("".join(parts), tuple(spans))
