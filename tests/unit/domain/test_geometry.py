import pytest

from app.domain.geometry import BoundingBox, pixels_to_points, union_box


def test_pixels_to_points_at_300_dpi() -> None:
    assert pixels_to_points(300, 150, 600, 60, dpi=300) == BoundingBox(72.0, 36.0, 144.0, 14.4)


def test_pixels_to_points_at_150_dpi() -> None:
    assert pixels_to_points(300, 150, 600, 60, dpi=150) == BoundingBox(144.0, 72.0, 288.0, 28.8)


@pytest.mark.parametrize("dpi", [0, -72])
def test_non_positive_dpi_is_rejected(dpi: int) -> None:
    with pytest.raises(ValueError, match="dpi"):
        pixels_to_points(1, 1, 1, 1, dpi=dpi)


@pytest.mark.parametrize(
    ("x", "y", "width", "height"),
    [(-1, 0, 1, 1), (0, -1, 1, 1), (0, 0, -1, 1), (0, 0, 1, -1)],
)
def test_negative_box_values_are_rejected(x: float, y: float, width: float, height: float) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BoundingBox(x, y, width, height)


def test_box_edges() -> None:
    box = BoundingBox(10, 20, 30, 5)

    assert (box.right, box.bottom) == (40, 25)


def test_union_box_encloses_all_boxes() -> None:
    union = union_box([BoundingBox(10, 20, 30, 10), BoundingBox(50, 18, 20, 15)])

    assert union == BoundingBox(10, 18, 60, 15)


def test_union_of_one_box_is_that_box() -> None:
    box = BoundingBox(1, 2, 3, 4)

    assert union_box([box]) == box


def test_union_of_nothing_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        union_box([])
