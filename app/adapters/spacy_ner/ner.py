"""Ner backed by a spaCy pipeline."""

from typing import Self

from spacy.language import Language

from app.domain.extraction import EntitySpan
from app.ports.ner import Ner


class SpacyNer(Ner):
    """Finds PERSON entities with a loaded spaCy pipeline."""

    def __init__(self, nlp: Language) -> None:
        """Initializes the NER.

        Args:
            nlp: A pipeline with an ``ner`` component.
        """
        self._nlp = nlp

    @classmethod
    def load(cls, model: str) -> Self:  # noqa: DOC501, DOC503
        """Loads an installed pipeline, keeping only what NER needs.

        Args:
            model: Name of the installed spaCy pipeline package.

        Returns:
            The NER adapter.
        """
        raise NotImplementedError

    def find_persons(self, text: str) -> list[EntitySpan]:  # noqa: DOC501, DOC503
        """Finds the PERSON entities in ``text``.

        Args:
            text: The text to analyse.

        Returns:
            Every PERSON span, as offsets into ``text``, in order.
        """
        raise NotImplementedError
