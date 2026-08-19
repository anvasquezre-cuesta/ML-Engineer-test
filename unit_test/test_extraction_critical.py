"""High-signal tests for the extraction correctness requirements."""

from dataclasses import dataclass
import json

import httpx
import pymupdf
import pytest

from app.api.dependencies import get_extraction_service
from app.config import Settings
from app.main import app
from app.models.domain import OCRDocument, OCRPage, OCRWord, PersonMention
from app.models.schemas import BoundingBox, NamePair
from app.services.bbox_service import OCRBoundingBoxService
from app.services.extraction_service import DocumentExtractionService
from app.services.fuzzy_service import TheFuzzMatchingService
from app.services.ner_service import SpacyNERService
from app.services.ocr_service import TesseractOCRService


def make_pdf(page_count: int = 2) -> bytes:
    """Create a real 72-by-72-point PDF without relying on sample files."""

    with pymupdf.open() as document:
        for _ in range(page_count):
            document.new_page(width=72, height=72)
        return document.tobytes()


def ocr_result(text: str) -> dict[str, list[object]]:
    return {
        "text": [text],
        "conf": ["95"],
        "left": [20],
        "top": [40],
        "width": [60],
        "height": [20],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
        "word_num": [1],
    }


def test_ocr_processes_page_zero_and_every_page_in_pdf_coordinates() -> None:
    """Mock Tesseract, but exercise real PDF rendering and coordinate math."""

    calls = 0

    def fake_tesseract(*args: object, **kwargs: object) -> dict[str, list[object]]:
        nonlocal calls
        calls += 1
        return ocr_result(f"Person{calls}")

    service = TesseractOCRService(
        Settings(_env_file=None, ocr_dpi=144),
        image_to_data=fake_tesseract,
    )

    result = service.extract(make_pdf(page_count=2))

    assert calls == 2
    assert [page.page_number for page in result.pages] == [0, 1]
    assert [page.text for page in result.pages] == ["Person1", "Person2"]
    box = result.pages[0].words[0].bounding_box
    # At 144 DPI, the image has two pixels per PDF point.
    assert (box.x, box.y, box.width, box.height) == pytest.approx(
        (10, 20, 30, 10)
    )
    assert result.pages[0].words[0].confidence == pytest.approx(0.95)


@dataclass(frozen=True)
class FakeEntity:
    text: str
    label_: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class FakeDocument:
    ents: tuple[FakeEntity, ...]


class FakeNLP:
    def __init__(self, entities: tuple[FakeEntity, ...]) -> None:
        self.entities = entities

    def __call__(self, text: str) -> FakeDocument:
        return FakeDocument(ents=self.entities)


def test_ner_keeps_only_people_with_page_and_occurrence_offsets() -> None:
    """Mock spaCy inference while retaining the production NER adapter."""

    text = "Maria met Maria at Acme"
    nlp = FakeNLP(
        (
            FakeEntity("Maria", "PERSON", 0, 5),
            FakeEntity("Maria", "PERSON", 10, 15),
            FakeEntity("Acme", "ORG", 19, 23),
        )
    )
    service = SpacyNERService(Settings(_env_file=None), nlp=nlp)

    mentions = service.extract_people(
        OCRPage(page_number=2, text=text, words=())
    )

    assert [
        (mention.name, mention.page_number, mention.start, mention.end)
        for mention in mentions
    ] == [
        ("Maria", 2, 0, 5),
        ("Maria", 2, 10, 15),
    ]


def make_word(
    text: str,
    start: int,
    end: int,
    x: float,
    *,
    line_number: int = 1,
) -> OCRWord:
    return OCRWord(
        text=text,
        bounding_box=BoundingBox(
            page_number=0,
            x=x,
            y=20 * line_number,
            width=30,
            height=10,
        ),
        confidence=0.95,
        start=start,
        end=end,
        block_number=1,
        paragraph_number=1,
        line_number=line_number,
        word_number=1,
    )


def test_bounding_box_merges_the_complete_multiword_mention() -> None:
    page = OCRPage(
        page_number=0,
        text="Maria Gonzalez",
        words=(
            make_word("Maria", 0, 5, 10),
            make_word("Gonzalez", 6, 14, 45),
        ),
    )
    document = OCRDocument(pages=(page,))

    located = OCRBoundingBoxService(Settings(_env_file=None)).locate(
        document,
        (PersonMention(name="Maria Gonzalez", page_number=0, start=0, end=14),),
    )

    assert len(located) == 1
    assert located[0].bounding_box == BoundingBox(
        page_number=0,
        x=10,
        y=20,
        width=65,
        height=10,
    )


def test_bounding_box_fuzzy_fallback_never_joins_different_lines() -> None:
    page = OCRPage(
        page_number=0,
        text="Marta Maria\nGonzalez",
        words=(
            make_word("Marta", 0, 5, 10),
            make_word("Maria", 6, 11, 45),
            make_word("Gonzalez", 12, 20, 10, line_number=2),
        ),
    )

    located = OCRBoundingBoxService(Settings(_env_file=None)).locate(
        OCRDocument(pages=(page,)),
        (PersonMention(name="Maria Gonzalez", page_number=0, start=0, end=5),),
    )

    assert located == ()


def make_fuzzy_service(threshold: float = 0.90) -> TheFuzzMatchingService:
    return TheFuzzMatchingService(
        Settings(_env_file=None, fuzzy_match_threshold=threshold)
    )


def test_fuzzy_matching_handles_case_accents_punctuation_and_ocr_noise() -> None:
    exact = make_fuzzy_service().match(
        ["MARÍA-GONZÁLEZ"],
        [NamePair(first_name="Maria", last_name="Gonzalez")],
    )
    noisy = make_fuzzy_service(threshold=0.85).match(
        ["Marla Gonzalez"],
        [NamePair(first_name="Maria", last_name="Gonzalez")],
    )

    assert exact[0].matched_name == "Maria Gonzalez"
    assert exact[0].score == 1.0
    assert 0.85 <= noisy[0].score < 1.0


def test_fuzzy_matching_uses_full_names_not_substrings() -> None:
    matches = make_fuzzy_service().match(
        ["Maria"],
        [NamePair(first_name="Maria", last_name="Gonzalez")],
    )

    assert matches == ()


@pytest.mark.asyncio
async def test_extract_http_path_runs_real_pipeline_with_mocked_models() -> None:
    """Exercise HTTP validation through the fixed response using no ML downloads."""

    settings = Settings(_env_file=None, ocr_dpi=144)
    service = DocumentExtractionService(
        ocr_service=TesseractOCRService(
            settings,
            image_to_data=lambda *args, **kwargs: ocr_result("MARÍA-GONZÁLEZ"),
        ),
        ner_service=SpacyNERService(
            settings,
            nlp=FakeNLP((FakeEntity("MARÍA-GONZÁLEZ", "PERSON", 0, 14),)),
        ),
        bounding_box_service=OCRBoundingBoxService(settings),
        fuzzy_matching_service=TheFuzzMatchingService(settings),
    )
    app.dependency_overrides[get_extraction_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/extract",
                files={
                    "pdf_file": ("scan.pdf", make_pdf(page_count=1), "text/plain")
                },
                data={
                    "names": json.dumps(
                        [{"first_name": "Maria", "last_name": "Gonzalez"}]
                    )
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "extracted_names": [
            {
                "name": "MARÍA-GONZÁLEZ",
                "bounding_box": {
                    "page_number": 0,
                    "x": 10.0,
                    "y": 20.0,
                    "width": 30.0,
                    "height": 10.0,
                },
            }
        ],
        "fuzzy_matches": [
            {
                "extracted_name": "MARÍA-GONZÁLEZ",
                "matched_name": "Maria Gonzalez",
                "score": 1.0,
            }
        ],
    }
