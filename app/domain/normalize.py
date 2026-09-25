"""Normalization of person names for comparison."""

import unicodedata

EDGE_PUNCTUATION = ".,;:!?()[]{}\"'‘’“”«»"

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
# Letters that NFKD leaves intact, so accent stripping would miss them.
_UNDECOMPOSED = str.maketrans(
    {
        "Ł": "L",
        "ł": "l",
        "Ø": "O",
        "ø": "o",
        "Đ": "D",
        "đ": "d",
        "Æ": "AE",
        "æ": "ae",
        "Œ": "OE",
        "œ": "oe",
        "ı": "i",
    }
)


def normalize_name(text: str) -> str:
    """Returns ``text`` in a form that ignores case, accents and OCR noise.

    Letters are casefolded and stripped of accents, including letters such as
    ``ł`` and ``ø`` that Unicode does not decompose. Typographic apostrophes
    become ``'``, punctuation around each token is removed and whitespace is
    collapsed to single spaces.

    Args:
        text: A name as written or recognized.

    Returns:
        The normalized name.
    """
    plain = text.translate(_APOSTROPHES).translate(_UNDECOMPOSED).casefold()
    decomposed = unicodedata.normalize("NFKD", plain)
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    tokens = (token.strip(EDGE_PUNCTUATION) for token in letters.split())
    return " ".join(token for token in tokens if token)
