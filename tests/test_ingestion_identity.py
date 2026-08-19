from uuid import UUID

from app.models.ingestion import ValidatedPDFUpload
from app.services.ingestion_service import create_ingestion_job


def make_upload() -> ValidatedPDFUpload:
    return ValidatedPDFUpload(
        filename="meeting_minutes.pdf",
        content=b"%PDF-valid-for-model-test",
        page_count=2,
    )


def test_each_ingestion_receives_a_unique_identifier() -> None:
    upload = make_upload()

    first_job = create_ingestion_job(upload)
    second_job = create_ingestion_job(upload)

    assert isinstance(first_job.ingestion_id, UUID)
    assert first_job.ingestion_id != second_job.ingestion_id
    assert first_job.pdf is upload


def test_identifier_generation_can_be_controlled_in_tests() -> None:
    expected_id = UUID("12345678-1234-5678-1234-567812345678")

    job = create_ingestion_job(make_upload(), id_factory=lambda: expected_id)

    assert job.ingestion_id == expected_id
