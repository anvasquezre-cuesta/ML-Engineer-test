"""Fuzzy-match extracted names against the requested name pairs (scores 0..1)."""

import re
import unicodedata

from rapidfuzz import fuzz

from app.config import get_settings

_TITLES = frozenset({"dr", "mr", "mrs", "ms", "miss", "prof"})


def _normalize(name: str) -> str:
    """Lowercase name without accents, apostrophes, punctuation or titles."""
    text = unicodedata.normalize("NFKD", name.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’]", "", text)
    words = re.sub(r"\W+", " ", text).split()
    return " ".join(w for w in words if w not in _TITLES)


def _by_key(names: list[str]) -> dict[str, str]:
    """Map normalized key -> first original name; empty keys are dropped."""
    keys: dict[str, str] = {}
    for name in names:
        if key := _normalize(name):
            keys.setdefault(key, name)
    return keys


def fuzzy_match_names(
    extracted_names: list[str],
    query_names: list[dict],
    threshold: float | None = None,
) -> list[dict]:
    """Return matches as ``{"extracted_name", "matched_name", "score"}``.

    ``threshold=None`` uses ``get_settings().fuzzy_threshold``.
    """
    if threshold is None:
        threshold = get_settings().fuzzy_threshold
    wanted = _by_key([f"{q['first_name']} {q['last_name']}" for q in query_names])
    hits = []
    for e_key, e_name in _by_key(extracted_names).items():
        for w_key, w_name in wanted.items():
            best = max(fuzz.ratio(e_key, w_key), fuzz.token_sort_ratio(e_key, w_key))
            # Filter on the raw score; round only the output.
            if best / 100 >= threshold:
                hits.append((round(best / 100, 4), e_name, w_name))
    hits.sort(key=lambda h: (-h[0], h[1], h[2]))
    return [{"extracted_name": e, "matched_name": w, "score": s} for s, e, w in hits]
