"""The verified sample questions and the frozen OCR text they refer to."""

import pathlib

import pydantic

DATA_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "rag_eval"


class Evidence(pydantic.BaseModel):
    """Where a question's answer is stated.

    Attributes:
        document: Document key, e.g. ``company_memo.pdf``.
        page: 0-based page number.
        quote: Text copied verbatim from the page's OCR.
    """

    document: str
    page: int
    quote: str


class Question(pydantic.BaseModel):
    """A verified question about the sample PDFs.

    Attributes:
        id: Stable identifier.
        question: The question text.
        answer: The expected answer; ``None`` when the documents do not
            answer it.
        evidence: Where the answer is stated; empty when unanswerable.
    """

    id: str
    question: str
    answer: str | None
    evidence: list[Evidence]


class Page(pydantic.BaseModel):
    """Frozen OCR text of one sample page.

    Attributes:
        document: Document key.
        page: 0-based page number.
        text: The page text as the service builds it.
    """

    document: str
    page: int
    text: str


class _Questions(pydantic.BaseModel):
    """Shape of ``samples.json``.

    Attributes:
        questions: The questions.
    """

    questions: list[Question]


class _Pages(pydantic.BaseModel):
    """Shape of ``ocr_pages.json``.

    Attributes:
        pages: The pages.
    """

    pages: list[Page]


def questions() -> list[Question]:
    """Loads the verified sample questions.

    Returns:
        Every question, answerable or not.
    """
    raw = (DATA_DIR / "samples.json").read_text(encoding="utf-8")
    return _Questions.model_validate_json(raw).questions


def pages() -> list[Page]:
    """Loads the frozen OCR text of the sample PDFs.

    Returns:
        One entry per page.
    """
    raw = (DATA_DIR / "ocr_pages.json").read_text(encoding="utf-8")
    return _Pages.model_validate_json(raw).pages
