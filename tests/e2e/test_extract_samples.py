import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.settings import Settings
from app.main import create_app
from app.models.schemas import ExtractionResponse
from tests.conftest import SAMPLE_PAGE_COUNTS, sample_bytes

pytestmark = pytest.mark.integration

GOLDEN = json.loads(
    (Path(__file__).parents[1] / "golden" / "persons.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def client(
    env_settings: Settings, tesseract_cmd: str | None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    # The app also opens the vector store at startup; keep it out of the repo.
    store = tmp_path_factory.mktemp("chroma")
    settings = env_settings.model_copy(update={"vector_store_path": str(store)})
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture(scope="module")
def responses(client: TestClient) -> dict[str, ExtractionResponse]:
    results = {}
    for name in SAMPLE_PAGE_COUNTS:
        response = client.post(
            "/api/extract",
            files={"pdf_file": (name, sample_bytes(name), "application/pdf")},
            data={"names": "[]"},
        )
        assert response.status_code == 200, response.text
        results[name] = ExtractionResponse.model_validate(response.json())
    return results


@pytest.mark.parametrize(("name", "pages"), SAMPLE_PAGE_COUNTS.items())
def test_contract_pages_and_coordinates(
    responses: dict[str, ExtractionResponse], name: str, pages: int
) -> None:
    body = responses[name]

    assert {e.bounding_box.page_number for e in body.extracted_names} == set(range(pages))
    for entry in body.extracted_names:
        box = entry.bounding_box
        assert box.x >= 0 and box.x + box.width <= 612
        assert box.y >= 0 and box.y + box.height <= 792
    assert body.fuzzy_matches == []


def test_repeated_names_get_one_entry_per_mention(
    responses: dict[str, ExtractionResponse],
) -> None:
    golden_count = sum(
        Counter(page["persons"])["Richard Hernandez"]
        for page in GOLDEN["pages"]
        if page["document"] == "meeting_minutes.pdf"
    )
    entries = [
        e for e in responses["meeting_minutes.pdf"].extracted_names if e.name == "Richard Hernandez"
    ]

    assert len(entries) == golden_count == 5
    assert len({(e.bounding_box.page_number, e.bounding_box.y) for e in entries}) == 5


def test_requested_names_are_fuzzy_matched(client: TestClient) -> None:
    names = [
        {"first_name": "Margaret", "last_name": "Thompson"},
        {"first_name": "María", "last_name": "García"},
        {"first_name": "Ana", "last_name": "Lopez"},
    ]

    response = client.post(
        "/api/extract",
        files={"pdf_file": ("memo.pdf", sample_bytes("company_memo.pdf"), "application/pdf")},
        data={"names": json.dumps(names)},
    )

    matches = ExtractionResponse.model_validate(response.json()).fuzzy_matches
    matched = {m.matched_name for m in matches}
    assert matched == {"Margaret Thompson", "María García"}
    assert all(m.score >= 0.90 for m in matches)
