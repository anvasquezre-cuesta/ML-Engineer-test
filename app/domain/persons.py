"""Person mentions: where NER found a name in page text, and where it sits on the page."""

from dataclasses import dataclass

from app.domain.geometry import BoundingBox


@dataclass(frozen=True, slots=True)
class PersonSpan:
    """A person name found at ``text[start:end]`` of a page's text."""

    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError(f"span must satisfy 0 <= start < end, got [{self.start}, {self.end})")


@dataclass(frozen=True, slots=True)
class NameOccurrence:
    """One real occurrence of a name on a page, boxed in PDF points."""

    name: str
    page_index: int
    box: BoundingBox
