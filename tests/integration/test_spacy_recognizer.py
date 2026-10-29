import pytest

from app.domain.errors import NerModelUnavailable
from app.infrastructure.settings import Settings
from app.infrastructure.spacy_recognizer import SpacyPersonNameRecognizer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def recognizer(env_settings: Settings) -> SpacyPersonNameRecognizer:
    return SpacyPersonNameRecognizer(env_settings.ner_model)


def test_only_people_are_returned(recognizer: SpacyPersonNameRecognizer) -> None:
    text = "Margaret Thompson met NovaTech Solutions in London on March 15, 2024."

    spans = recognizer.recognize(text)

    assert [span.text for span in spans] == ["Margaret Thompson"]
    assert text[spans[0].start : spans[0].end] == "Margaret Thompson"


def test_honorifics_are_trimmed(recognizer: SpacyPersonNameRecognizer) -> None:
    text = "Prepared by: Dr. Olivia Chambers, Research Director"

    spans = recognizer.recognize(text)

    assert [span.text for span in spans] == ["Olivia Chambers"]
    assert text[spans[0].start : spans[0].end] == "Olivia Chambers"


def test_empty_text_has_no_people(recognizer: SpacyPersonNameRecognizer) -> None:
    assert recognizer.recognize("") == []


def test_unknown_model_is_unavailable() -> None:
    with pytest.raises(NerModelUnavailable, match="xx_no_such_model"):
        SpacyPersonNameRecognizer("xx_no_such_model")
