"""Validate the future extraction endpoint's names field without HTTP coupling."""

import json

from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.models.schemas import NamePair


class InvalidNamesError(ValueError):
    """The names field is not a JSON list of nonblank name pairs."""


class NamesLimitError(ValueError):
    """The names field exceeds its byte or item limit."""


_name_pairs = TypeAdapter(list[NamePair])


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant")


def parse_names(value: str, settings: Settings) -> list[NamePair]:
    """Validate a decoded form field, preserving names exactly as supplied.

    The byte limit is the UTF-8 size of the decoded field, including JSON syntax.
    This check happens after multipart parsing and does not replace the ASGI body
    limit. Errors deliberately do not include the potentially sensitive input.
    """
    if not isinstance(value, str):
        raise InvalidNamesError("Invalid names field")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise InvalidNamesError("Invalid names field") from None
    if size > settings.max_names_bytes:
        raise NamesLimitError("Names field exceeds the configured byte limit")

    try:
        decoded = json.loads(value, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        raise InvalidNamesError("Invalid names field") from None
    if not isinstance(decoded, list):
        raise InvalidNamesError("Invalid names field")
    if len(decoded) > settings.max_names_count:
        raise NamesLimitError("Names field exceeds the configured item limit")
    try:
        names = _name_pairs.validate_python(decoded)
    except ValidationError:
        raise InvalidNamesError("Invalid names field") from None
    if any(not pair.first_name.strip() or not pair.last_name.strip() for pair in names):
        raise InvalidNamesError("Invalid names field")
    if any(len(pair.first_name) > settings.max_name_chars or len(pair.last_name) > settings.max_name_chars for pair in names):
        raise NamesLimitError("A name exceeds the configured character limit")
    try:
        for pair in names:
            pair.first_name.encode("utf-8")
            pair.last_name.encode("utf-8")
    except UnicodeEncodeError:
        # JSON escape sequences can decode to isolated Unicode surrogates.
        raise InvalidNamesError("Invalid names field") from None
    return names
