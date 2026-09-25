"""Router for asynchronous extraction and ingestion jobs."""

from typing import Annotated
from typing import cast

import fastapi

from app import config
from app.api import extract as extract_api
from app.domain import extraction
from app.domain import jobs
from app.domain import pdf_validation
from app.domain import rag
from app.models import schemas
from app.service_layer import jobs as job_service

router = fastapi.APIRouter()


def submit_use_case(request: fastapi.Request) -> job_service.SubmitJob:
    """Returns the submit use case built at startup.

    Args:
        request: The current request.

    Returns:
        The use case.
    """
    return cast(job_service.SubmitJob, request.app.state.submit_job)


def query_use_case(request: fastapi.Request) -> job_service.QueryJobs:
    """Returns the job query use case built at startup.

    Args:
        request: The current request.

    Returns:
        The use case.
    """
    return cast(job_service.QueryJobs, request.app.state.query_jobs)


Submit = Annotated[job_service.SubmitJob, fastapi.Depends(submit_use_case)]
Query = Annotated[job_service.QueryJobs, fastapi.Depends(query_use_case)]
Limits = Annotated[
    config.UploadSettings, fastapi.Depends(extract_api.upload_settings)
]


@router.post("/jobs/extract", status_code=202)
async def submit_extract(
    pdf_file: fastapi.UploadFile,
    names: Annotated[str, fastapi.Form()],
    submit: Submit,
    limits: Limits,
    document_key: Annotated[str | None, fastapi.Form()] = None,
) -> schemas.JobAccepted:
    """Queues the extraction of a PDF; poll ``GET /api/jobs/{job_id}``.

    Args:
        pdf_file: The uploaded PDF.
        names: JSON list of the names to match against.
        submit: The submit use case.
        limits: Upload limits.
        document_key: Key to record the document under, if not the
            filename.

    Returns:
        The queued job.
    """
    try:
        queries = extract_api.parse_names(names)
        content = await pdf_file.read(limits.max_bytes + 1)
    finally:
        await pdf_file.close()
    pdf_validation.validate_pdf(content, limits.max_bytes)
    job = await submit(
        jobs.JobKind.EXTRACT, content, document_key, pdf_file.filename, queries
    )
    return _accepted(job)


@router.post("/jobs/ingest", status_code=202)
async def submit_ingest(
    pdf_file: fastapi.UploadFile,
    submit: Submit,
    limits: Limits,
    document_key: Annotated[str | None, fastapi.Form()] = None,
) -> schemas.JobAccepted:
    """Queues the ingestion of a PDF; poll ``GET /api/jobs/{job_id}``.

    Args:
        pdf_file: The uploaded PDF.
        submit: The submit use case.
        limits: Upload limits.
        document_key: Key to index the document under, if not the
            filename.

    Returns:
        The queued job.
    """
    try:
        content = await pdf_file.read(limits.max_bytes + 1)
    finally:
        await pdf_file.close()
    pdf_validation.validate_pdf(content, limits.max_bytes)
    job = await submit(
        jobs.JobKind.INGEST, content, document_key, pdf_file.filename
    )
    return _accepted(job)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, query: Query) -> schemas.JobRecord:
    """Returns a job's state and, once it succeeded, its result.

    Args:
        job_id: Id of the job.
        query: The job query use case.

    Returns:
        The job.
    """
    job, result = await query.get(job_id)
    return _record(job, result)


@router.get("/jobs")
async def list_jobs(
    query: Query,
    status: jobs.JobStatus = jobs.JobStatus.DEAD_LETTERED,
    limit: Annotated[int, fastapi.Query(ge=1, le=500)] = 100,
) -> list[schemas.JobRecord]:
    """Lists jobs in one state, most recently updated first.

    Args:
        query: The job query use case.
        status: The state; dead-lettered jobs by default.
        limit: Most jobs to return.

    Returns:
        The jobs, without results.
    """
    found = await query.list_by_status(status, limit)
    return [_record(job, None) for job in found]


def _accepted(job: jobs.Job) -> schemas.JobAccepted:
    """Maps a queued job to the submit response.

    Args:
        job: The queued job.

    Returns:
        The response body.
    """
    return schemas.JobAccepted(
        job_id=job.job_id,
        status=str(job.status),
        document_key=job.document_key or "",
    )


def _record(
    job: jobs.Job,
    result: extraction.ExtractionResult | rag.IngestResult | None,
) -> schemas.JobRecord:
    """Maps a job and its result to the API shape.

    Args:
        job: The job.
        result: Its result, if it succeeded.

    Returns:
        The response body.
    """
    extracted = None
    ingested = None
    if isinstance(result, extraction.ExtractionResult):
        extracted = extract_api.extraction_response(result)
    elif isinstance(result, rag.IngestResult):
        ingested = schemas.IngestResponse(
            status=str(result.status), chunks_stored=result.chunks_stored
        )
    return schemas.JobRecord(
        job_id=job.job_id,
        kind=str(job.kind),
        status=str(job.status),
        dead_lettered=job.dead_lettered,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        document_key=job.document_key,
        last_error_code=job.last_error_code,
        last_error_message=job.last_error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        extraction=extracted,
        ingestion=ingested,
    )
