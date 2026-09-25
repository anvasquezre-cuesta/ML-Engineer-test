"""Name normalization: case, accents and OCR noise must not matter."""

import pytest

from app.domain import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("María González", "maria gonzalez"),
        ("  JOSÉ \n Núñez ", "jose nunez"),
        ("Łukasz Østergaard", "lukasz ostergaard"),
        ("Kevin O’Brien", "kevin o'brien"),
        ("Olivia Chambers,", "olivia chambers"),
    ],
)
def test_normalized_forms_compare_equal(raw: str, expected: str) -> None:
    assert normalize.normalize_name(raw) == expected
