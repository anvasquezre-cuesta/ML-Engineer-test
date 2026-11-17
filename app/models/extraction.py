"""Internal, page-local contracts for the future extraction pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonSpan:
    """Person text and its [start, end) character offsets within one OCR page.

    The consumer must also check the offsets against the particular page's text;
    this object alone does not identify a page or verify the text at that range.
    """

    text: str
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("A person span must contain text")
        if (
            type(self.char_start) is not int
            or type(self.char_end) is not int
            or self.char_start < 0
            or self.char_end <= self.char_start
        ):
            raise ValueError("A person span must have a non-empty, non-negative range")
