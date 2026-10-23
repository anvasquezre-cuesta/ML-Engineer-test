import pytest

from app.domain.geometry import box_px_to_pt, px_to_pt, word_to_points
from app.domain.models import Box
from tests.fakes import ocr_word


@pytest.mark.parametrize(
    ("pixels", "dpi", "points"),
    [
        (300, 300, 72.0),  # one inch
        (150, 150, 72.0),
        (2550, 300, 612.0),  # US Letter width
        (3300, 300, 792.0),  # US Letter height
        (250, 300, 60.0),  # a typical left margin
        (0, 300, 0.0),
    ],
)
def test_px_to_pt(pixels: float, dpi: int, points: float) -> None:
    assert px_to_pt(pixels, dpi) == pytest.approx(points)


def test_box_conversion_scales_every_edge_without_flipping_y() -> None:
    box = box_px_to_pt(Box(x0=250, y0=400, x1=550, y1=450), dpi=300)

    assert (box.x0, box.y0, box.x1, box.y1) == pytest.approx((60.0, 96.0, 132.0, 108.0))
    assert box.width == pytest.approx(72.0)
    assert box.height == pytest.approx(12.0)


def test_word_conversion_keeps_text_confidence_and_line() -> None:
    word = word_to_points(ocr_word("Robert", 300, 600, 600, 660, line=7, conf=91.5), dpi=150)

    assert word.text == "Robert"
    assert word.confidence == 91.5
    assert word.line_key == (1, 1, 7)
    assert (word.box.x0, word.box.y0) == pytest.approx((144.0, 288.0))
