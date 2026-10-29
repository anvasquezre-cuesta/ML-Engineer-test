"""Boxes in PDF points (72/inch), top-left origin, y growing down (TRD ADR-003)."""

from collections.abc import Sequence
from dataclasses import dataclass

POINTS_PER_INCH = 72


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An axis-aligned rectangle in PDF points."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0:
            raise ValueError(f"box values must be non-negative, got {self}")

    @property
    def right(self) -> float:
        """x of the right edge."""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """y of the bottom edge."""
        return self.y + self.height


def pixels_to_points(x_px: float, y_px: float, w_px: float, h_px: float, dpi: int) -> BoundingBox:
    """Convert a pixel box of an image rendered at ``dpi`` into PDF points (``px * 72 / dpi``).

    The only pixel→point conversion in the codebase; called once, in the OCR adapter.
    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    return BoundingBox(
        x_px * POINTS_PER_INCH / dpi,
        y_px * POINTS_PER_INCH / dpi,
        w_px * POINTS_PER_INCH / dpi,
        h_px * POINTS_PER_INCH / dpi,
    )


def union_box(boxes: Sequence[BoundingBox]) -> BoundingBox:
    """Smallest box enclosing every box given."""
    if not boxes:
        raise ValueError("cannot take the union of an empty sequence of boxes")
    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.right for b in boxes)
    bottom = max(b.bottom for b in boxes)
    return BoundingBox(left, top, right - left, bottom - top)
