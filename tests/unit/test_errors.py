"""Guards that keep error codes and HTTP statuses from drifting apart."""

from app.api.errors import ERROR_STATUS
from app.api.errors import FRAMEWORK_CODES
from app.domain.errors import AppError


def _concrete_codes() -> list[str]:
    """Returns the code of every AppError subclass that declares one.

    Returns:
        The codes, found recursively, including duplicates.
    """
    codes: list[str] = []
    pending = list(AppError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if "code" in vars(cls):
            codes.append(cls.code)
    return codes


def test_codes_are_unique() -> None:
    codes = _concrete_codes()
    assert len(codes) == len(set(codes))


def test_status_map_covers_exactly_the_known_codes() -> None:
    assert set(ERROR_STATUS) == set(_concrete_codes()) | FRAMEWORK_CODES
