"""Every domain error code has an HTTP status in the API."""

from app.api import errors as api_errors
from app.domain import errors as domain_errors


def _concrete_codes() -> list[str]:
    """Returns the code of every AppError subclass that declares one.

    Returns:
        The codes, found recursively.
    """
    codes: list[str] = []
    pending = list(domain_errors.AppError.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if "code" in vars(cls):
            codes.append(cls.code)
    return codes


def test_status_map_covers_exactly_the_known_codes() -> None:
    assert (
        set(api_errors.ERROR_STATUS)
        == set(_concrete_codes()) | api_errors.FRAMEWORK_CODES
    )
