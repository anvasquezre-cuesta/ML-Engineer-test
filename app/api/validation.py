"""Validation helpers for multipart document requests."""

import json
import logging
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import PurePosixPath
from typing import Annotated

import pymupdf
from fastapi import Depends, File, Form, HTTPException, UploadFile, status
from pydantic import TypeAdapter, ValidationError

from app.config import Settings, get_settings
from app.models.ingestion import ValidatedPDFUpload
from app.models.schemas import NamePair

logger = logging.getLogger(__name__)
name_list_adapter = TypeAdapter(list[NamePair])


@dataclass(frozen=True, slots=True)
class ValidatedExtractionRequest:
    """Validated data passed from the HTTP layer to the extraction pipeline."""

    pdf_content: bytes
    names: tuple[NamePair, ...]


def parse_names(raw_names: str, max_names: int) -> tuple[NamePair, ...]:
    """Parse and validate the JSON string contained in the ``names`` form field."""

    try:
        payload = json.loads(raw_names)
    except JSONDecodeError as exc:
        logger.warning("Names rejected: malformed JSON")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="names must be valid JSON",
        ) from exc

    if not isinstance(payload, list):
        logger.warning("Names rejected: expected a JSON array")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="names must be a JSON array",
        )

    if len(payload) > max_names:
        logger.warning(
            "Names rejected: count %s exceeds limit %s", len(payload), max_names
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"names cannot contain more than {max_names} entries",
        )

    try:
        parsed_names = name_list_adapter.validate_python(payload)
    except ValidationError as exc:
        logger.warning("Names rejected: one or more entries are invalid")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="each name must contain non-empty first_name and last_name strings",
        ) from exc

    normalized_names: list[NamePair] = []
    for name in parsed_names:
        first_name = name.first_name.strip()
        last_name = name.last_name.strip()
        if not first_name or not last_name:
            logger.warning("Names rejected: blank first_name or last_name")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="first_name and last_name cannot be blank",
            )
        normalized_names.append(
            NamePair(first_name=first_name, last_name=last_name)
        )

    return tuple(normalized_names)


def validate_pdf_content(content: bytes) -> int:
    """Validate PDF bytes and return the number of readable pages."""

    if b"%PDF-" not in content[:1024]:
        logger.warning("PDF rejected: missing PDF signature")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="pdf_file must contain a PDF document",
        )

    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass:
                logger.warning("PDF rejected: document is password protected")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="password-protected PDFs are not supported",
                )
            if document.page_count == 0:
                logger.warning("PDF rejected: document contains no pages")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="pdf_file must contain at least one page",
                )
            return document.page_count
    except HTTPException:
        raise
    except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
        logger.warning("PDF rejected: document is corrupt or unreadable")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pdf_file is corrupt or unreadable",
        ) from exc


def normalize_upload_filename(filename: str | None) -> str:
    """Remove client-provided path components from an upload filename."""

    normalized = PurePosixPath((filename or "").replace("\\", "/")).name.strip()
    return normalized[:255] or "uploaded.pdf"


async def read_and_validate_pdf_upload(
    pdf_file: UploadFile,
    max_size_bytes: int,
) -> ValidatedPDFUpload:
    """Read and validate a PDF upload while always closing its handle."""

    try:
        if pdf_file.size is not None and pdf_file.size > max_size_bytes:
            logger.warning(
                "PDF rejected: declared size %s exceeds limit %s",
                pdf_file.size,
                max_size_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"pdf_file cannot exceed {max_size_bytes} bytes",
            )

        try:
            content = await pdf_file.read(max_size_bytes + 1)
        except Exception as exc:
            logger.exception("PDF upload could not be read")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_file could not be read",
            ) from exc

        if not content:
            logger.warning("PDF rejected: upload is empty")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="pdf_file cannot be empty",
            )
        if len(content) > max_size_bytes:
            logger.warning(
                "PDF rejected: uploaded content exceeds limit %s", max_size_bytes
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"pdf_file cannot exceed {max_size_bytes} bytes",
            )

        page_count = validate_pdf_content(content)
        return ValidatedPDFUpload(
            filename=normalize_upload_filename(pdf_file.filename),
            content=content,
            page_count=page_count,
        )
    finally:
        try:
            await pdf_file.close()
        except Exception:
            logger.warning("PDF upload handle could not be closed", exc_info=True)


async def read_and_validate_pdf(
    pdf_file: UploadFile,
    max_size_bytes: int,
) -> bytes:
    """Backward-compatible helper returning only validated PDF bytes."""

    validated_upload = await read_and_validate_pdf_upload(
        pdf_file,
        max_size_bytes=max_size_bytes,
    )
    return validated_upload.content


async def validate_ingestion_request(
    pdf_file: Annotated[
        UploadFile,
        File(
            title="Scanned PDF",
            description=(
                "PDF document to index. The file is validated by content, must "
                "contain at least one page, and cannot be password protected."
            ),
            media_type="application/pdf",
        ),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ValidatedPDFUpload:
    """Validate the PDF accepted by ``POST /api/ingest``."""

    validated_upload = await read_and_validate_pdf_upload(
        pdf_file,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    logger.info(
        "Ingestion request validated: filename=%s, pdf_size=%s bytes, pages=%s",
        validated_upload.filename,
        validated_upload.size_bytes,
        validated_upload.page_count,
    )
    return validated_upload


async def validate_extraction_request(
    pdf_file: Annotated[
        UploadFile,
        File(
            title="Scanned PDF",
            description=(
                "PDF document to process. The file is validated by content, must "
                "contain at least one page, and cannot be password protected."
            ),
            media_type="application/pdf",
        ),
    ],
    names: Annotated[
        str,
        Form(
            title="Names to match",
            description=(
                "JSON-encoded array of people to fuzzy-match against detected "
                "names. Each item requires first_name and last_name."
            ),
            examples=[
                '[{"first_name":"Maria","last_name":"Gonzalez"}]'
            ],
        ),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ValidatedExtractionRequest:
    """Validate and normalize all fields accepted by ``POST /api/extract``."""

    pdf_content = await read_and_validate_pdf(
        pdf_file,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    parsed_names = parse_names(names, max_names=settings.max_names_per_request)
    logger.info(
        "Extraction request validated: pdf_size=%s bytes, names=%s",
        len(pdf_content),
        len(parsed_names),
    )
    return ValidatedExtractionRequest(pdf_content=pdf_content, names=parsed_names)
