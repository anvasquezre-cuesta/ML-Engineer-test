import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://test-qdrant:6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "test_documents")

    settings = Settings()

    assert settings.qdrant_url == "http://test-qdrant:6333"
    assert settings.qdrant_collection == "test_documents"


def test_extraction_settings_defaults_and_environment(monkeypatch):
    defaults = Settings()
    assert defaults.max_request_bytes == 21 * 1024 * 1024
    assert defaults.max_names_bytes == 64 * 1024
    assert defaults.max_names_count == 1000
    assert defaults.fuzzy_threshold == 0.90

    monkeypatch.setenv("MAX_REQUEST_BYTES", "12345")
    monkeypatch.setenv("MAX_NAMES_BYTES", "250")
    monkeypatch.setenv("MAX_NAMES_COUNT", "3")
    monkeypatch.setenv("FUZZY_THRESHOLD", "0.75")
    settings = Settings()
    assert (settings.max_request_bytes, settings.max_names_bytes, settings.max_names_count) == (12345, 250, 3)
    assert settings.fuzzy_threshold == 0.75


@pytest.mark.parametrize("field", ["max_request_bytes", "max_names_bytes", "max_names_count"])
@pytest.mark.parametrize("value", [0, -1, "not-a-number"])
def test_extraction_limits_must_be_positive_integers(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_fuzzy_threshold_accepts_inclusive_bounds(value):
    assert Settings(fuzzy_threshold=value).fuzzy_threshold == value


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), "invalid"])
def test_fuzzy_threshold_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        Settings(fuzzy_threshold=value)


@pytest.mark.parametrize("field,value", [
    ("extract_max_in_flight", 0), ("extract_upload_timeout_seconds", 0),
    ("extract_upload_timeout_seconds", float("inf")), ("max_extracted_names", 0),
    ("max_fuzzy_comparisons", -1), ("max_name_chars", 0), ("max_fuzzy_work_units", 0),
])
def test_extraction_flow_limits_are_validated(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_extraction_flow_limits_can_be_set_from_environment(monkeypatch):
    monkeypatch.setenv("EXTRACT_MAX_IN_FLIGHT", "3")
    monkeypatch.setenv("EXTRACT_UPLOAD_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("MAX_EXTRACTED_NAMES", "40")
    monkeypatch.setenv("MAX_FUZZY_COMPARISONS", "200")
    monkeypatch.setenv("MAX_NAME_CHARS", "50")
    monkeypatch.setenv("MAX_FUZZY_WORK_UNITS", "4000")
    settings = Settings()
    assert (settings.extract_max_in_flight, settings.extract_upload_timeout_seconds) == (3, 15)
    assert (settings.max_extracted_names, settings.max_fuzzy_comparisons) == (40, 200)
    assert (settings.max_name_chars, settings.max_fuzzy_work_units) == (50, 4000)


@pytest.mark.parametrize("value", [0, 1, 2, 3])
def test_name_recovery_levels_are_configurable_from_environment(monkeypatch, value):
    monkeypatch.setenv("NER_NAME_RECOVERY_PASSES", str(value))
    assert Settings().ner_name_recovery_passes == value
    assert Settings(ner_name_recovery_passes=value).ner_name_recovery_passes == value


def test_name_recovery_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NER_NAME_RECOVERY_PASSES", raising=False)
    assert Settings().ner_name_recovery_passes == 0


@pytest.mark.parametrize("value", [-1, 4, True, False, 1.0, "1.0", "yes", ""])
def test_invalid_name_recovery_levels_are_rejected(value):
    with pytest.raises(ValidationError):
        Settings(ner_name_recovery_passes=value)


@pytest.mark.parametrize("options", [
    {"ingest_chunk_tokens": 2}, {"ingest_chunk_tokens": 257}, {"ingest_overlap_tokens": 126},
    {"embedding_query_max_tokens": 257}, {"ingest_max_chunks": 0}, {"ingest_max_in_flight": 0},
    {"qdrant_read_retries": 6}, {"qdrant_timeout_seconds": 0},
    {"ingest_max_page_chars": 100, "ingest_max_document_chars": 50},
    {"embedding_job_timeout_seconds": float("inf")},
])
def test_ingestion_limits_are_validated(options):
    with pytest.raises(ValidationError):
        Settings(**options)
