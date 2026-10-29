import pytest

from app.domain.names import normalize_name, strip_leading_honorific
from app.domain.persons import PersonSpan


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MARÍA GONZÁLEZ", "maria gonzalez"),
        ("Dr. Kevin O’Brien", "kevin o brien"),
        ("Al-Rashidi", "al rashidi"),
        ("  Margaret \t  Thompson\n", "margaret thompson"),
        ("Gonzalez, Maria", "gonzalez maria"),
        ("Prof Olivia Chambers", "olivia chambers"),
        ("Mrs. Ms. Park", "park"),
        ("", ""),
        ("Dr.", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_honorific_is_only_dropped_at_the_start() -> None:
    assert normalize_name("Elizabeth Ms Park") == "elizabeth ms park"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dr. Olivia Chambers", "Olivia Chambers"),
        ("Prof. Michael O’Sullivan", "Michael O’Sullivan"),
        ("Mrs Elizabeth Park", "Elizabeth Park"),
        ("Dr. Prof. Hans Weber", "Hans Weber"),
        ("Drew Carey", "Drew Carey"),
        ("Mrsmith Jones", "Mrsmith Jones"),
    ],
)
def test_strip_leading_honorific_moves_the_start(text: str, expected: str) -> None:
    source = f"Prepared by: {text}, Director"
    start = source.index(text)
    span = PersonSpan(start, start + len(text), text)

    stripped = strip_leading_honorific(span)

    assert stripped is not None
    assert stripped.text == expected
    assert source[stripped.start : stripped.end] == expected


def test_strip_leading_honorific_drops_a_bare_honorific() -> None:
    assert strip_leading_honorific(PersonSpan(0, 3, "Dr.")) is None
