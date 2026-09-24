"""spaCy adapter: only PERSON entities leave the adapter."""

from typing import cast

import pytest
import spacy
from spacy.pipeline import EntityRuler

from app.adapters.spacy_ner.ner import SpacyNer
from app.domain.extraction import EntitySpan

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="adapter not built yet"
)


def test_only_person_entities_are_returned() -> None:
    nlp = spacy.blank("en")
    ruler = cast(EntityRuler, nlp.add_pipe("entity_ruler"))
    ruler.add_patterns(
        [
            {"label": "PERSON", "pattern": "Anna Berg"},
            {"label": "ORG", "pattern": "Acme Corp"},
            {"label": "PERSON", "pattern": "Lucas"},
            {"label": "GPE", "pattern": "Paris"},
        ]
    )

    text = "Anna Berg of Acme Corp met Lucas in Paris."

    spans = SpacyNer(nlp).find_persons(text)

    assert spans == [
        EntitySpan(start=0, end=9, text="Anna Berg"),
        EntitySpan(start=27, end=32, text="Lucas"),
    ]
