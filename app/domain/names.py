"""Person-name normalization shared by matching and evaluation (TRD ADR-005)."""

import re
import unicodedata

from app.domain.persons import PersonSpan

HONORIFICS = frozenset({"dr", "prof", "mr", "mrs", "ms"})

# An honorific token, optional dot, then whitespace: "Dr. ", "Mrs ", never "Drew".
_LEADING_HONORIFIC = re.compile(
    r"(?:{})\.?\s+".format("|".join(sorted(HONORIFICS, key=len, reverse=True))),
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """Fold case/accents/punctuation and drop leading honorifics: ``Dr. María`` → ``maria``."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    spaced = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in without_marks)
    tokens = spaced.split()
    while tokens and tokens[0] in HONORIFICS:
        tokens.pop(0)
    return " ".join(tokens)


def strip_leading_honorific(span: PersonSpan) -> PersonSpan | None:
    """Move the span start past leading honorifics; ``None`` if no name is left."""
    start, text = span.start, span.text
    while match := _LEADING_HONORIFIC.match(text):
        start += match.end()
        text = text[match.end() :]
    if not normalize_name(text):
        return None
    return PersonSpan(start, span.end, text)
