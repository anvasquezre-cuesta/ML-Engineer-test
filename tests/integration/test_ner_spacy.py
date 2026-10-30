from app.services.ner_service import extract_names


def test_ac_ner_01_only_persons():
    text = "Maria Gonzalez met Acme Corp in Paris on Monday."

    assert extract_names(text) == ["Maria Gonzalez"]
