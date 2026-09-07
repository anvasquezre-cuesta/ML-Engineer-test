from dataclasses import dataclass, field


@dataclass(frozen=True)
class Word:
    """One OCR token. Coordinates are PDF points, origin top-left, y down."""

    text: str
    x: float
    y: float
    width: float
    height: float
    line: tuple[int, int, int]  # (block, paragraph, line) from tesseract


@dataclass
class Page:
    index: int  # 0-based
    width: float
    height: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        lines: list[list[str]] = []
        current_key = None
        for w in self.words:
            if w.line != current_key:
                lines.append([])
                current_key = w.line
            lines[-1].append(w.text)
        return "\n".join(" ".join(line) for line in lines)


@dataclass(frozen=True)
class Box:
    page: int
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source: str
    score: float
