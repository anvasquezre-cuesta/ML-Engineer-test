"""Port that scores how similar two person names are."""

import abc


class NameMatcher(abc.ABC):
    """Full-string name similarity robust to case, accents and OCR noise."""

    @abc.abstractmethod
    def similarity(self, candidate: str, reference: str) -> float:
        """Scores how similar ``candidate`` is to ``reference``.

        Args:
            candidate: A name extracted from the document.
            reference: A name supplied by the caller.

        Returns:
            Similarity in 0..1, where 1 means the names are equal after
            normalization.
        """
