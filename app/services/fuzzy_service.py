"""Compare full person names without losing their original spelling."""

import unicodedata

from thefuzz import fuzz

from app.models.schemas import FuzzyMatch, NamePair


def normalize_name(value: str) -> str:
    """Ignore case and accents; remove apostrophes and treat punctuation as spaces."""
    value = unicodedata.normalize("NFKD", value.casefold())
    parts = []
    for char in value:
        if unicodedata.category(char).startswith("M"):
            continue
        if char in "'\u2019\u02bc":
            continue
        parts.append(char if char.isalnum() else " ")
    return " ".join("".join(parts).split())


def match_names(extracted_names: list[str], query_names: list[NamePair], threshold: float) -> list[FuzzyMatch]:
    """Return every distinct qualifying string pair in deterministic input order."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("The fuzzy threshold must be between 0 and 1")
    matches = []
    seen = set()
    queries = []
    for query in query_names:
        requested = f"{query.first_name.strip()} {query.last_name.strip()}"
        queries.append((requested, normalize_name(requested)))
    for extracted in dict.fromkeys(extracted_names):
        normalized_extracted = normalize_name(extracted)
        if not normalized_extracted:
            continue
        for requested, normalized_requested in queries:
            pair = (extracted, requested)
            if pair in seen:
                continue
            seen.add(pair)
            if not normalized_requested:
                continue
            score = fuzz.ratio(normalized_extracted, normalized_requested) / 100.0
            if score >= threshold:
                matches.append(FuzzyMatch(extracted_name=extracted, matched_name=requested, score=score))
    return matches


def fuzzy_match_names(extracted_names: list[str], query_names: list[dict]) -> list[dict]:
    """Compatibility wrapper for synchronous callers using the configured threshold."""
    from app.core.config import get_settings

    names = [NamePair.model_validate(query) for query in query_names]
    return [match.model_dump() for match in match_names(extracted_names, names, get_settings().fuzzy_threshold)]
