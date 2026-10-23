"""``NameMatcher`` backed by thefuzz's ``token_sort_ratio``.

Whole-string and order-insensitive: tokens are sorted, then compared as one
string, so ``Thompson Margaret`` equals ``Margaret Thompson`` but a first name
alone does not match a full name. ``token_set_ratio`` and ``partial_ratio``
were rejected because they score ``Jennifer`` vs ``Jennifer Liu`` at 100 (the
substring trick the brief warns about).

String similarity cannot tell OCR noise (``Rlchard``, 0.94) from a different
person (``Park`` vs ``Parker``, 0.93), so every pair at or above the threshold
is returned with its score for the reviewer to judge.
"""

from collections.abc import Sequence

from thefuzz import fuzz

from app.domain.models import NameMatch
from app.domain.text import normalize_name


class FuzzyMatcher:
    def __init__(self, threshold: float) -> None:
        self._threshold = threshold

    def match(self, extracted: Sequence[str], candidates: Sequence[str]) -> list[NameMatch]:
        """One entry per distinct (extracted, candidate) pair at or above the threshold.

        Repeated occurrences of a name are collapsed: ``FuzzyMatch`` carries no
        location, so duplicates would add rows without information. Each
        occurrence keeps its own box in ``extracted_names``.
        """
        normalized_candidates = [(c, normalize_name(c)) for c in dict.fromkeys(candidates)]
        matches = []
        for name in dict.fromkeys(extracted):
            normalized = normalize_name(name)
            if not normalized:
                continue
            for candidate, normalized_candidate in normalized_candidates:
                score = fuzz.token_sort_ratio(normalized, normalized_candidate) / 100
                if score >= self._threshold:
                    matches.append(NameMatch(extracted=name, candidate=candidate, score=score))
        return sorted(matches, key=lambda m: (-m.score, m.extracted, m.candidate))
