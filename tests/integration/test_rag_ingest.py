import huggingface_hub
import pytest

from app.config import get_settings
from app.services.embedding_service import get_embeddings, get_query_embedding
from app.services.rag_service import ingest
from app.services.vector_service import _collection, search_similar
from tests.unit.test_ocr_service import FakeEngine, blank_pdf, row

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
pytestmark = pytest.mark.skipif(
    not isinstance(huggingface_hub.try_to_load_from_cache(MODEL, "config.json"), str),
    reason="MiniLM is not in the Hugging Face cache",
)

TEXT_A = (
    "Tomato seedlings need plenty of sunlight, loose soil and regular watering. "
    "Gardeners usually plant them after the last frost, spacing each plant about "
    "sixty centimetres apart. Mulch keeps the roots cool and reduces weeds, while "
    "a stake or cage supports the stems as the fruit grows heavy. Remove the "
    "lower leaves to improve airflow and prevent fungal disease during humid "
    "weeks, and feed the plants with compost every two weeks until harvest. "
    "Water at the base of the plant in the morning so the leaves stay dry."
)
TEXT_B = (
    "A satellite stays in orbit because it is falling around the Earth at high "
    "speed. Lower orbits need greater velocity and complete a lap in about ninety "
    "minutes, whereas geostationary satellites circle once a day at the altitude "
    "of thirty-six thousand kilometres. Engineers correct the trajectory with "
    "short thruster burns, and atmospheric drag slowly pulls low satellites back "
    "toward the planet unless they carry enough fuel to climb again. Solar panels "
    "supply power and radiators release the heat that the electronics produce."
)


def engine_for(text):
    return FakeEngine(*(row(word, left=10 * i) for i, word in enumerate(text.split())))


@pytest.fixture
def minilm(tmp_path, monkeypatch):
    """Real MiniLM (offline) and Chroma in tmp_path; caches cleared around the test."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("OCR_DPI", "72")
    get_settings.cache_clear()
    _collection.cache_clear()
    yield
    get_settings.cache_clear()
    _collection.cache_clear()


def test_ac_int_01_reingest_a_b_a_with_minilm(minilm):
    pdf_a, pdf_b = blank_pdf(), blank_pdf(2)
    n_a = ingest(pdf_a, "a.pdf", engine_for(TEXT_A), get_embeddings).chunks_stored
    assert _collection().count() == n_a

    n_b = ingest(pdf_b, "b.pdf", engine_for(TEXT_B), get_embeddings).chunks_stored
    assert _collection().count() == n_a + n_b

    short_a = TEXT_A.split(". ")[0]  # same PDF bytes, fewer chunks: stale ones must go
    n_short = ingest(pdf_a, "a.pdf", engine_for(short_a), get_embeddings).chunks_stored
    assert n_short < n_a
    assert _collection().count() == n_short + n_b

    query = get_query_embedding("How fast must a satellite travel to stay in orbit?")
    assert search_similar(query, top_k=1)[0]["filename"] == "b.pdf"


def test_ac_emb_01_minilm_vectors_are_normalized(minilm):
    vectors = get_embeddings(["a", "b"])
    query = get_query_embedding("a")

    assert [len(v) for v in vectors] == [384, 384]
    for vector in (*vectors, query):
        assert sum(x * x for x in vector) ** 0.5 == pytest.approx(1.0, abs=1e-6)
    assert max(abs(q - v) for q, v in zip(query, vectors[0], strict=True)) <= 1e-5
