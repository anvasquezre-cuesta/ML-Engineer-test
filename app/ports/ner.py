"""Port that finds person names in text."""

import abc

from app.domain.extraction import EntitySpan


class Ner(abc.ABC):
    """Named-entity recognition restricted to people."""

    @abc.abstractmethod
    def find_persons(self, text: str) -> list[EntitySpan]:  # noqa: DOC502
        """Finds the PERSON entities in ``text``.

        Args:
            text: The text to analyse.

        Returns:
            Every PERSON span, as offsets into ``text``, in order.

        Raises:
            NerError: If the NER pipeline fails.
        """
