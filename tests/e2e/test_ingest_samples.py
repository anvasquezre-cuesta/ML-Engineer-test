from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.domain.chunking import Chunk, document_id_for
from app.infrastructure.chroma_vector_store import ChromaVectorStore
from app.infrastructure.sentence_transformer_embedder import SentenceTransformerEmbedder
from app.infrastructure.settings import Settings
from app.main import create_app
from tests.conftest import SAMPLE_PAGE_COUNTS, sample_bytes

pytestmark = pytest.mark.integration

MEMO, MINUTES, REPORT = "company_memo.pdf", "meeting_minutes.pdf", "research_report.pdf"


@pytest.fixture(scope="module")
def settings(
    env_settings: Settings, tesseract_cmd: str | None, tmp_path_factory: pytest.TempPathFactory
) -> Settings:
    path = tmp_path_factory.mktemp("chroma")
    return env_settings.model_copy(update={"vector_store_path": str(path)})


@pytest.fixture(scope="module")
def ingested(settings: Settings) -> Iterator[tuple[dict[str, int], list[Chunk]]]:
    """Ingest memo, minutes, report, then memo again; return the counts and the store."""
    counts: dict[str, int] = {}
    with TestClient(create_app(settings)) as client:
        for name in (MEMO, MINUTES, REPORT, MEMO):
            response = client.post(
                "/api/ingest", files={"pdf_file": (name, sample_bytes(name), "application/pdf")}
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "ingested"
            counts[name] = response.json()["chunks_stored"]
    # The app released the store at shutdown; open it again to inspect what was stored.
    store = ChromaVectorStore(settings.vector_store_path, settings.vector_store_collection)
    try:
        yield counts, store.all_chunks()
    finally:
        store.close()


def _ids_of(chunks: list[Chunk], name: str) -> list[str]:
    document_id = document_id_for(sample_bytes(name))
    return sorted(c.id for c in chunks if c.document_id == document_id)


def test_a_second_document_does_not_overwrite_the_first(
    ingested: tuple[dict[str, int], list[Chunk]],
) -> None:
    counts, chunks = ingested

    assert len(chunks) == sum(counts.values())
    prefixes = {name: {i.split(":")[0] for i in _ids_of(chunks, name)} for name in counts}
    assert all(len(prefix) == 1 for prefix in prefixes.values())
    assert len(set.union(*prefixes.values())) == 3


def test_reingesting_the_same_pdf_keeps_exactly_one_copy(
    ingested: tuple[dict[str, int], list[Chunk]],
) -> None:
    counts, chunks = ingested
    document_id = document_id_for(sample_bytes(MEMO))

    assert _ids_of(chunks, MEMO) == sorted(f"{document_id}:{i}" for i in range(counts[MEMO]))


@pytest.mark.parametrize("name", [MINUTES, REPORT])
def test_every_page_is_indexed_within_the_token_budget(
    ingested: tuple[dict[str, int], list[Chunk]], settings: Settings, name: str
) -> None:
    _, chunks = ingested
    document_chunks = [c for c in chunks if c.document_id == document_id_for(sample_bytes(name))]
    embedder = SentenceTransformerEmbedder(settings.embedding_model)

    assert {c.page for c in document_chunks} == set(range(SAMPLE_PAGE_COUNTS[name]))
    assert {c.file_name for c in document_chunks} == {name}
    for chunk in document_chunks:
        assert embedder.count_tokens(chunk.text) <= settings.chunk_max_tokens
