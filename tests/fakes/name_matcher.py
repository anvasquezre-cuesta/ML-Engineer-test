"""Fake NameMatcher with scripted scores."""

from collections.abc import Mapping

from app.ports.name_matcher import NameMatcher


class ScriptedNameMatcher(NameMatcher):
    """Returns scripted scores; unscripted pairs score 0."""

    def __init__(self, scores: Mapping[tuple[str, str], float]) -> None:
        """Initializes the matcher.

        Args:
            scores: Score per ``(candidate, reference)`` pair.
        """
        self._scores = scores

    def similarity(self, candidate: str, reference: str) -> float:
        """Returns the scripted score of the pair.

        Args:
            candidate: A name extracted from the document.
            reference: A name supplied by the caller.

        Returns:
            The scripted score, or 0 for an unscripted pair.
        """
        return self._scores.get((candidate, reference), 0.0)
