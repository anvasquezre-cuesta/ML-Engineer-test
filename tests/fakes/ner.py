"""Fake Ner that tags a fixed list of exact strings."""

from collections.abc import Collection

from app.domain.extraction import EntitySpan
from app.ports.ner import Ner


class ExactNer(Ner):
    """Tags every exact, case-sensitive occurrence of known person strings.

    Anything not written exactly as listed is missed, like a real model
    missing a variant spelling.
    """

    def __init__(self, persons: Collection[str]) -> None:
        """Initializes the NER.

        Args:
            persons: Strings to tag as PERSON wherever they occur.
        """
        self._persons = persons

    def find_persons(self, text: str) -> list[EntitySpan]:
        """Returns every occurrence of the known strings in ``text``.

        Args:
            text: The text to analyse.

        Returns:
            The spans, ordered by start offset.
        """
        spans = []
        for person in self._persons:
            start = text.find(person)
            while start != -1:
                end = start + len(person)
                spans.append(EntitySpan(start=start, end=end, text=person))
                start = text.find(person, end)
        return sorted(spans, key=lambda span: span.start)
