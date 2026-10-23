"""The real spaCy adapter. Skipped when the model is not installed."""

import pytest

from app.adapters.spacy_ner import SpacyNER
from app.core.config import NERSettings
from tests.integration.conftest import requires_spacy_model

pytestmark = [pytest.mark.integration, requires_spacy_model]


def test_returns_only_people_one_list_per_text_in_order(spacy_ner: SpacyNER) -> None:
    results = spacy_ner.find_persons(
        [
            "- Anna Kowalski was named to the Forbes 30 Under 30",
            "BOARD OF DIRECTORS - MEETING MINUTES",
            "- Dr. Aisha Patel, Independent Director",
        ]
    )

    assert [[e.text for e in entities] for entities in results] == [
        ["Anna Kowalski"],  # Forbes is an ORG
        [],
        ["Aisha Patel"],  # the model leaves the title out
    ]


def test_character_offsets_point_into_the_input(spacy_ner: SpacyNER) -> None:
    name = "Kevin O\N{RIGHT SINGLE QUOTATION MARK}Brien"
    text = f"APAC region. {name} noted potential regulatory"

    ((entity,),) = spacy_ner.find_persons([text])

    assert text[entity.start_char : entity.end_char] == name


def test_missing_model_fails_with_a_clear_message() -> None:
    with pytest.raises(RuntimeError, match="not installed"):
        SpacyNER(NERSettings(model="xx_no_such_model"))
