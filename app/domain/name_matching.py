"""Fuzzy matching of extracted names against requested names (TRD ADR-005).

Full-string similarity only: ``max(ratio, token_sort_ratio)`` on normalized names, so
``Ana`` never matches ``Ana María Rodríguez`` the way a substring scorer would.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.domain.names import normalize_name

SCORE_DECIMALS = 4


@dataclass(frozen=True, slots=True)
class RequestedName:
    """A person the caller is checking for."""

    first_name: str
    last_name: str

    def __post_init__(self) -> None:
        if not self.first_name.strip() or not self.last_name.strip():
            raise ValueError("first_name and last_name must be non-blank")

    @property
    def full_name(self) -> str:
        """The comparison string ``"{first} {last}"``."""
        return f"{self.first_name} {self.last_name}"


@dataclass(frozen=True, slots=True)
class NameMatch:
    """An extracted name (as printed) that matches a requested name, score in 0..1."""

    extracted_name: str
    matched_name: str
    score: float


def similarity(a: str, b: str) -> float:
    """Order-tolerant full-string similarity of two normalized names, in 0..1."""
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b)) / 100


def match_names(
    extracted: Sequence[str], requested: Sequence[RequestedName], threshold: float
) -> list[NameMatch]:
    """Return every (extracted, requested) pair scoring ≥ threshold, best first."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be within [0, 1], got {threshold}")

    candidates = [(name, normalize_name(name)) for name in dict.fromkeys(extracted)]
    targets = [
        (full, normalize_name(full)) for full in dict.fromkeys(r.full_name for r in requested)
    ]

    matches = []
    for original, normalized in candidates:
        for full_name, target in targets:
            if not normalized or not target:
                continue
            score = round(similarity(normalized, target), SCORE_DECIMALS)
            if score >= threshold:
                matches.append(NameMatch(original, full_name, score))
    return sorted(matches, key=lambda m: (-m.score, m.extracted_name, m.matched_name))
