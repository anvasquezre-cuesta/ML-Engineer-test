"""NameMatcher backed by rapidfuzz."""

from app.ports.name_matcher import NameMatcher


class RapidFuzzNameMatcher(NameMatcher):
    """Whole-name similarity, order-insensitive, robust to OCR digit noise."""

    def similarity(self, candidate: str, reference: str) -> float:  # noqa: DOC501, DOC503
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
        raise NotImplementedError
