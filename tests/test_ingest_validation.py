import io

import httpx
import pymupdf
import pytest
from fastapi import UploadFile

from app.api.validation import read_and_validate_pdf_upload
from app.main import app


def make_pdf(page_count: int = 1) -> bytes:
    with pymupdf.open() as document:
        for _ in range(page_count):
            document.new_page()
        return document.tobytes()


async def post_ingest(content: bytes, filename: str = "scan.pdf") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.post(
            "/api/ingest",
            files={"pdf_file": (filename, content, "application/pdf")},
        )


@pytest.mark.asyncio
async def test_ingest_accepts_a_readable_pdf() -> None:
    response = await post_ingest(make_pdf(page_count=2))

    assert response.status_code == 200
    assert response.json() == {"status": "validated", "chunks_stored": 0}


@pytest.mark.asyncio
async def test_ingest_rejects_non_pdf_content() -> None:
    response = await post_ingest(b"not a pdf")

    assert response.status_code == 415
    assert response.json() == {"detail": "pdf_file must contain a PDF document"}


@pytest.mark.asyncio
async def test_ingest_rejects_an_empty_upload() -> None:
    response = await post_ingest(b"")

    assert response.status_code == 400
    assert response.json() == {"detail": "pdf_file cannot be empty"}


@pytest.mark.asyncio
async def test_validated_upload_contains_safe_metadata_and_closes_file() -> None:
    content = make_pdf(page_count=2)
    upload = UploadFile(
        filename="../../meeting_minutes.pdf",
        file=io.BytesIO(content),
        size=len(content),
    )

    validated = await read_and_validate_pdf_upload(
        upload,
        max_size_bytes=len(content) + 1,
    )

    assert validated.filename == "meeting_minutes.pdf"
    assert validated.content == content
    assert validated.size_bytes == len(content)
    assert validated.page_count == 2
    assert upload.file.closed


def test_ingest_openapi_describes_pdf_validation() -> None:
    operation = app.openapi()["paths"]["/api/ingest"]["post"]
    request_reference = operation["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]["$ref"]
    request_name = request_reference.rsplit("/", 1)[-1]
    request_properties = app.openapi()["components"]["schemas"][request_name][
        "properties"
    ]

    assert operation["summary"] == "Validate and ingest a scanned PDF"
    assert "validated by content" in request_properties["pdf_file"]["description"]
    assert {"400", "413", "415", "422"}.issubset(operation["responses"])
