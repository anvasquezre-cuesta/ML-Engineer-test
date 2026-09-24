"""Router for asynchronous extraction and ingestion jobs."""

from typing import Annotated
from typing import cast

import fastapi

from app import config
from app.api import extract as extract_api
from app.domain import jobs
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

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


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

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, query: Query) -> schemas.JobRecord:
    """Returns a job's state and, once it succeeded, its result.

    Args:
        job_id: Id of the job.
        query: The job query use case.

    Returns:
        The job.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


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

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError
