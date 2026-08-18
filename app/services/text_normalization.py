"""Text normalization shared by name-location and fuzzy-match services."""

import re
import unicodedata

_NON_ALPHANUMERIC = re.compile(r"[\W_]+", flags=re.UNICODE)


def normalize_name(value: str) -> str:
    """Normalize case, accents, punctuation, and whitespace for comparison."""

    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    without_punctuation = _NON_ALPHANUMERIC.sub(" ", without_accents.casefold())
    return " ".join(without_punctuation.split())
