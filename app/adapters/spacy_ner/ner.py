"""Ner backed by a spaCy pipeline."""

from typing import Self

import spacy
from spacy import language

from app.domain import errors
from app.domain import extraction
from app.ports import ner

PERSON = "PERSON"
UNUSED_COMPONENTS = ("tagger", "parser", "attribute_ruler", "lemmatizer")


class SpacyNer(ner.Ner):
    """Finds PERSON entities with a loaded spaCy pipeline.

    One pipeline instance is shared by every thread that calls
    ``find_persons``.
    """

    def __init__(self, nlp: language.Language) -> None:
        """Initializes the NER.

        Args:
            nlp: A pipeline with an ``ner`` component.
        """
        self._nlp = nlp

    @classmethod
    def load(cls, model: str) -> Self:
        """Loads an installed pipeline, keeping only what NER needs.

        Args:
            model: Name of the installed spaCy pipeline package.

        Returns:
            The NER adapter.

        Raises:
            errors.NerError: If the pipeline is not installed.
        """
        try:
            nlp = spacy.load(model, exclude=list(UNUSED_COMPONENTS))
        except OSError as exc:
            raise errors.NerError(
                f"spaCy pipeline {model!r} is not installed; set "
                "DOCINTEL_NER__MODEL to an installed pipeline."
            ) from exc
        return cls(nlp)

    def find_persons(self, text: str) -> list[extraction.EntitySpan]:
        """Finds the PERSON entities in ``text``.

        Args:
            text: The text to analyse.

        Returns:
            Every PERSON span, as offsets into ``text``, in order.

        Raises:
            errors.NerError: If the text exceeds the pipeline's ``max_length``.
        """
        try:
            doc = self._nlp(text)
        except ValueError as exc:
            raise errors.NerError() from exc
        return [
            extraction.EntitySpan(
                start=ent.start_char, end=ent.end_char, text=ent.text
            )
            for ent in doc.ents
            if ent.label_ == PERSON
        ]
