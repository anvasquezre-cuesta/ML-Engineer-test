"""NER: extract PERSON names (with their offsets) from page texts."""

import re
from functools import lru_cache
from typing import Protocol

import spacy

from app.config import get_settings

Span = tuple[str, int, int]  # (name, start, end) on the text of one page


class NameRecognizer(Protocol):
    def __call__(self, text: str) -> list[Span]: ...


@lru_cache
def _load_model(name: str):
    """Load a spaCy model once per name."""
    return spacy.load(name)


def spacy_persons(text: str) -> list[Span]:
    """PERSON entities from the configured spaCy model."""
    ents = _load_model(get_settings().ner_model)(text).ents
    return [(e.text, e.start_char, e.end_char) for e in ents if e.label_ == "PERSON"]


def _is_name(name: str, drop_all_caps: bool) -> bool:
    """Keep spans that look like a name: one line, 2+ words, not ALL CAPS."""
    return "\n" not in name and " " in name and not (drop_all_caps and name.isupper())


def _propagate(text: str, names: set[str], found: list[Span]) -> list[Span]:
    """Add every exact whole-word occurrence of ``names`` in ``text`` to ``found``."""
    hits = [
        (n, m.start(), m.end())
        for n in names
        for m in re.finditer(rf"(?<!\w){re.escape(n)}(?!\w)", text)
    ]
    return sorted(dict.fromkeys(found + hits), key=lambda s: (s[1], s[2]))


def find_person_spans(
    pages: list[str], recognizer: NameRecognizer | None = None
) -> list[list[Span]]:
    """Return person spans per page: filtered, plus names found on any page, sorted."""
    recognize = recognizer or spacy_persons
    drop_caps = get_settings().ner_drop_all_caps
    found = [
        [s for s in recognize(page) if _is_name(s[0], drop_caps)] for page in pages
    ]
    names = {n for spans in found for n, _, _ in spans}
    return [_propagate(page, names, f) for page, f in zip(pages, found, strict=True)]


def extract_names(text: str) -> list[str]:
    """Return the unique person names of ``text``, in order of appearance."""
    return list(dict.fromkeys(n for n, _, _ in find_person_spans([text])[0]))
