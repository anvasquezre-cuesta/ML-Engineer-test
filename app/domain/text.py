"""Name normalisation used before any similarity scoring.

Matching must be case-insensitive and robust to accents and OCR punctuation, so
both sides are reduced to lowercase ASCII-ish words first:

- ``casefold`` rather than ``lower`` (``Straße`` -> ``strasse``);
- NFKD then drop combining marks (``María`` -> ``maria``);
- letters NFKD does not decompose are folded explicitly (``Łukasz`` -> ``lukasz``);
- apostrophes are **deleted**, not turned into spaces: as a space, ``O'Brien``
  becomes two tokens and scores 56 against ``OBrien``;
- any other punctuation becomes a space (``Al-Rashidi`` -> ``al rashidi``).
"""

import re
import unicodedata

_UNDECOMPOSABLE = str.maketrans(
    {
        "ł": "l",
        "ø": "o",
        "đ": "d",
        "ð": "d",
        "þ": "th",
        "æ": "ae",
        "œ": "oe",
        "\N{LATIN SMALL LETTER DOTLESS I}": "i",
    }
)
_APOSTROPHES = re.compile(r"['`\N{RIGHT SINGLE QUOTATION MARK}\N{MODIFIER LETTER APOSTROPHE}]")
_OTHER_PUNCTUATION = re.compile(r"[^\w\s]|_")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name.casefold().translate(_UNDECOMPOSABLE))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _APOSTROPHES.sub("", text)
    text = _OTHER_PUNCTUATION.sub(" ", text)
    return " ".join(text.split())
