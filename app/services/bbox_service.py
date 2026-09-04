from app.models.domain import Box, Page
from app.services.fuzzy_service import normalize, similarity


def locate(name: str, page: Page, token_threshold: float) -> list[Box]:
    """Every place `name` appears on the page, as one box around its words.

    A name is a run of consecutive OCR words where each word fuzzy-matches the
    corresponding name token. The run may wrap once onto the next line, but never
    stitches words from unrelated parts of the page.
    """
    tokens = normalize(name).split()
    words = page.words
    if not tokens or len(words) < len(tokens):
        return []

    line_order = {}
    for w in words:
        line_order.setdefault(w.line, len(line_order))

    boxes = []
    i = 0
    while i <= len(words) - len(tokens):
        window = words[i : i + len(tokens)]
        if _same_or_next_line(window, line_order) and all(
            similarity(w.text, t) >= token_threshold for w, t in zip(window, tokens, strict=True)
        ):
            x = min(w.x for w in window)
            y = min(w.y for w in window)
            boxes.append(
                Box(
                    page=page.index,
                    x=x,
                    y=y,
                    width=max(w.x + w.width for w in window) - x,
                    height=max(w.y + w.height for w in window) - y,
                )
            )
            i += len(tokens)
        else:
            i += 1
    return boxes


def _same_or_next_line(window, line_order) -> bool:
    lines = sorted({line_order[w.line] for w in window})
    return len(lines) == 1 or (len(lines) == 2 and lines[1] == lines[0] + 1)
