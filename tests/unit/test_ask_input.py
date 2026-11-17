import pytest

from app.services.ask_input import InvalidQuestionError, normalize_question


def test_question_is_stripped_without_changing_its_content():
    assert normalize_question("  ¿Quién llegó? \n") == "¿Quién llegó?"


@pytest.mark.parametrize("question", ["", " \n\t", None, 12, "x" * 2001, " " + "x" * 2000])
def test_invalid_question_is_rejected_without_echoing_input(question):
    with pytest.raises(InvalidQuestionError, match="^Invalid question$"):
        normalize_question(question)


def test_question_at_contract_limit_is_not_truncated():
    assert normalize_question("x" * 2000) == "x" * 2000
