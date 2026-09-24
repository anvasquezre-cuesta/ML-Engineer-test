"""NameMatcher backed by rapidfuzz."""

import re

from rapidfuzz import fuzz

from app.domain import normalize
from app.ports import name_matcher

# Only for names: in IDs or dates these characters are real data.
_OCR_CONFUSIONS = str.maketrans({"1": "l", "0": "o", "5": "s", "|": "l"})
_LETTER = re.compile(r"[^\W\d_]")


def _fold_ocr_confusions(name: str) -> str:
    """Replaces digits OCR misreads for letters inside tokens with letters.

    Args:
        name: A normalized name.

    Returns:
        The name with ``1``, ``0``, ``5`` and ``|`` read as ``l``, ``o``,
        ``s`` and ``l`` in tokens that contain a letter.
    """
    return " ".join(
        token.translate(_OCR_CONFUSIONS) if _LETTER.search(token) else token
        for token in name.split()
    )


class RapidFuzzNameMatcher(name_matcher.NameMatcher):
    """Whole-name similarity, order-insensitive, robust to OCR digit noise."""

    def similarity(self, candidate: str, reference: str) -> float:
        """Scores how similar ``candidate`` is to ``reference``.

        Both names are normalized, then OCR digit-for-letter confusions are
        folded inside tokens that mix letters with digits or ``|``. The score
        is the indel similarity of the names with their tokens sorted, so
        word order does not matter but a partial name scores low.

        Args:
            candidate: A name extracted from the document.
            reference: A name supplied by the caller.

        Returns:
            Similarity in 0..1, where 1 means the names are equal after
            normalization.
        """
        return (
            fuzz.token_sort_ratio(
                _fold_ocr_confusions(normalize.normalize_name(candidate)),
                _fold_ocr_confusions(normalize.normalize_name(reference)),
            )
            / 100
        )
