"""Input normalization for the future question-answering service."""


class InvalidQuestionError(ValueError):
    """The question is empty or exceeds the public character limit."""


def normalize_question(question: str) -> str:
    """Reject invalid questions without truncating or exposing their contents."""
    if not isinstance(question, str) or len(question) > 2000:
        raise InvalidQuestionError("Invalid question")
    normalized = question.strip()
    if not normalized:
        raise InvalidQuestionError("Invalid question")
    return normalized
