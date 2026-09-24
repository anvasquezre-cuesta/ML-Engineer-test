"""spaCy adapter: only PERSON entities leave the adapter."""

from typing import cast

import spacy
from spacy import pipeline

from app.adapters.spacy_ner import ner
from app.domain import extraction


def test_only_person_entities_are_returned() -> None:
    nlp = spacy.blank("en")
    ruler = cast(pipeline.EntityRuler, nlp.add_pipe("entity_ruler"))
    ruler.add_patterns(
        [
            {"label": "PERSON", "pattern": "Anna Berg"},
            {"label": "ORG", "pattern": "Acme Corp"},
            {"label": "PERSON", "pattern": "Lucas"},
            {"label": "GPE", "pattern": "Paris"},
        ]
    )

    text = "Anna Berg of Acme Corp met Lucas in Paris."

    spans = ner.SpacyNer(nlp).find_persons(text)

    assert spans == [
        extraction.EntitySpan(start=0, end=9, text="Anna Berg"),
        extraction.EntitySpan(start=27, end=32, text="Lucas"),
    ]
