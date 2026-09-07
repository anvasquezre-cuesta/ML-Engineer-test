from types import SimpleNamespace

import pytest

from app.services import ner_service
from app.services.ner_service import SpacyNer, clean_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("John Smith's", "John Smith"),
        ("  María\nGonzález, ", "María González"),
        ("Q3 2024", ""),  # digits: OCR junk, not a person
        ("J", ""),
    ],
)
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_only_person_entities_are_kept(monkeypatch):
    ents = [
        SimpleNamespace(text="John Smith", label_="PERSON"),
        SimpleNamespace(text="Acme Corp", label_="ORG"),
        SimpleNamespace(text="Paris", label_="GPE"),
        SimpleNamespace(text="Monday", label_="DATE"),
        SimpleNamespace(text="Ana Ruiz", label_="PER"),  # multilingual model label
    ]
    monkeypatch.setattr(
        ner_service.spacy, "load", lambda *a, **k: lambda text: SimpleNamespace(ents=ents)
    )
    assert SpacyNer("whatever").person_names("...") == ["John Smith", "Ana Ruiz"]
