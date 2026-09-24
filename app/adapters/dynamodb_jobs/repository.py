"""Job repository on DynamoDB; every transition is a conditional update.

One item per job under ``JOB#{job id}``. A status index keyed by status and
update time lists jobs in one state, most recently updated first. Times are
stored as ISO 8601 UTC strings, which sort and compare chronologically.
"""

import asyncio
from collections.abc import Callable
import datetime
from typing import Any

from app.adapters.dynamodb_common import client as dynamodb
from app.domain import errors
from app.domain import extraction
from app.domain import jobs
from app.ports import job_repository

STATUS_INDEX = "status"
_CONDITION_FAILED = "ConditionalCheckFailedException"
_WAITING = (jobs.JobStatus.QUEUED, jobs.JobStatus.RETRYING)
_OPEN = (*_WAITING, jobs.JobStatus.RUNNING)


class DynamoDbJobRepository(job_repository.JobRepository):
    """Job store whose state changes are compare-and-set updates."""

    def __init__(self, client: Any, table: str) -> None:
        """Initializes the repository.

        Args:
            client: The boto3 DynamoDB client.
            table: Table name.
        """
        self._client = client
        self._table = table

    async def ensure_table(self) -> None:
        """Creates the table and its status index if they are missing.

        Raises:
            errors.JobStoreUnavailableError: If the table cannot be
                described or created.
        """
        try:
            await self._call(self._client.describe_table, TableName=self._table)
            return
        except errors.JobStoreUnavailableError as exc:
            missing = "ResourceNotFoundException"
            if not dynamodb.has_code(exc.__cause__, missing):
                raise
        await self._call(
            self._client.create_table,
            TableName=self._table,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": name, "AttributeType": "S"}
                for name in ("PK", "status", "updated_at")
            ],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": STATUS_INDEX,
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "updated_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        waiter = self._client.get_waiter("table_exists")
        await asyncio.to_thread(waiter.wait, TableName=self._table)

    async def create(self, job: jobs.Job) -> None:
        """Stores a new job; an existing id is never overwritten.

        Args:
            job: The job.
        """
        await self._call(
            self._client.put_item,
            TableName=self._table,
            Item=dynamodb.encode({"PK": _key(job.job_id), **_fields(job)}),
            ConditionExpression="attribute_not_exists(PK)",
        )

    async def get(self, job_id: str) -> jobs.Job | None:
        """Reads one job, consistently.

        Args:
            job_id: Id of the job.

        Returns:
            The job, if any.
        """
        response = await self._call(
            self._client.get_item,
            TableName=self._table,
            Key=dynamodb.encode({"PK": _key(job_id)}),
            ConsistentRead=True,
        )
        item = response.get("Item")
        return _job(dynamodb.decode(item)) if item else None

    async def list_by_status(
        self, status: jobs.JobStatus, limit: int
    ) -> list[jobs.Job]:
        """Lists jobs in one state, most recently updated first.

        The status index is eventually consistent.

        Args:
            status: The state.
            limit: Most jobs to return.

        Returns:
            The jobs.
        """
        response = await self._call(
            self._client.query,
            TableName=self._table,
            IndexName=STATUS_INDEX,
            KeyConditionExpression="#s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=dynamodb.encode({":s": str(status)}),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_job(dynamodb.decode(i)) for i in response.get("Items", [])]

    async def claim(
        self, job_id: str, lease_expires_at: datetime.datetime
    ) -> jobs.Job | None:
        """Moves a queued or retrying job to running, counting the attempt.

        Args:
            job_id: Id of the job.
            lease_expires_at: When the lease lapses (UTC).

        Returns:
            The claimed job, or ``None`` if it was not claimable.
        """
        return await self._move(
            job_id,
            _WAITING,
            {
                "status": str(jobs.JobStatus.RUNNING),
                "lease_expires_at": _time(lease_expires_at),
            },
            count_attempt=True,
        )

    async def mark_succeeded(
        self, job_id: str, result_key: str
    ) -> jobs.Job | None:
        """Moves a running job to succeeded.

        Args:
            job_id: Id of the job.
            result_key: Blob key of the result.

        Returns:
            The job, or ``None`` if it was not running.
        """
        return await self._move(
            job_id,
            (jobs.JobStatus.RUNNING,),
            {
                "status": str(jobs.JobStatus.SUCCEEDED),
                "result_key": result_key,
            },
        )

    async def mark_retrying(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a running job to retrying.

        Args:
            job_id: Id of the job.
            error_code: Code of the failure.
            error_message: Safe message of the failure.

        Returns:
            The job, or ``None`` if it was not running.
        """
        return await self._move(
            job_id,
            (jobs.JobStatus.RUNNING,),
            {
                "status": str(jobs.JobStatus.RETRYING),
                "last_error_code": error_code,
                "last_error_message": error_message,
            },
        )

    async def mark_dead_lettered(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a job that is not terminal to dead-lettered.

        Args:
            job_id: Id of the job.
            error_code: Code of the final failure.
            error_message: Safe message of the final failure.

        Returns:
            The job, or ``None`` if it was already terminal.
        """
        return await self._move(
            job_id,
            _OPEN,
            {
                "status": str(jobs.JobStatus.DEAD_LETTERED),
                "last_error_code": error_code,
                "last_error_message": error_message,
            },
        )

    async def list_expired_leases(
        self, now: datetime.datetime
    ) -> list[jobs.Job]:
        """Lists running jobs whose lease lapsed before ``now``.

        Args:
            now: The current time (UTC).

        Returns:
            The jobs.
        """
        found: list[jobs.Job] = []
        start: dict[str, Any] = {}
        while True:
            response = await self._call(
                self._client.query,
                TableName=self._table,
                IndexName=STATUS_INDEX,
                KeyConditionExpression="#s = :s",
                FilterExpression="lease_expires_at < :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues=dynamodb.encode(
                    {":s": str(jobs.JobStatus.RUNNING), ":now": _time(now)}
                ),
                **start,
            )
            found += [_job(dynamodb.decode(i)) for i in response["Items"]]
            if "LastEvaluatedKey" not in response:
                return found
            start = {"ExclusiveStartKey": response["LastEvaluatedKey"]}

    async def _move(
        self,
        job_id: str,
        allowed: tuple[jobs.JobStatus, ...],
        changes: dict[str, Any],
        count_attempt: bool = False,
    ) -> jobs.Job | None:
        """Applies ``changes`` only if the job is in an allowed state.

        Args:
            job_id: Id of the job.
            allowed: States the transition starts from.
            changes: Attributes to set.
            count_attempt: Whether to add one to ``attempts``.

        Returns:
            The updated job, or ``None`` if its state did not allow it.

        Raises:
            errors.JobStoreUnavailableError: If the update fails for another
                reason.
        """
        changes = {**changes, "updated_at": _time(_now())}
        names = {f"#a{i}": name for i, name in enumerate(changes)}
        values = {f":v{i}": value for i, value in enumerate(changes.values())}
        states = {f":s{i}": str(state) for i, state in enumerate(allowed)}
        update = "SET " + ", ".join(f"{n} = :v{i}" for i, n in enumerate(names))
        if count_attempt:
            update += " ADD attempts :one"
            values[":one"] = 1
        try:
            response = await self._call(
                self._client.update_item,
                TableName=self._table,
                Key=dynamodb.encode({"PK": _key(job_id)}),
                UpdateExpression=update,
                ConditionExpression=f"#status IN ({', '.join(states)})",
                ExpressionAttributeNames={**names, "#status": "status"},
                ExpressionAttributeValues=dynamodb.encode({**values, **states}),
                ReturnValues="ALL_NEW",
            )
        except errors.JobStoreUnavailableError as exc:
            if dynamodb.has_code(exc.__cause__, _CONDITION_FAILED):
                return None
            raise
        return _job(dynamodb.decode(response["Attributes"]))

    async def _call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Runs a blocking client call off the event loop.

        Args:
            method: The boto3 client method.
            **kwargs: Its parameters.

        Returns:
            The response.
        """
        return await dynamodb.call(
            method, errors.JobStoreUnavailableError, **kwargs
        )


def _now() -> datetime.datetime:
    """Returns the current time.

    Returns:
        The time (UTC).
    """
    return datetime.datetime.now(datetime.UTC)


def _key(job_id: str) -> str:
    """Returns a job's partition key.

    Args:
        job_id: Id of the job.

    Returns:
        ``JOB#{job id}``.
    """
    return f"JOB#{job_id}"


def _time(value: datetime.datetime) -> str:
    """Writes a time as a sortable UTC string.

    Args:
        value: An aware time.

    Returns:
        ISO 8601 in UTC.
    """
    return value.astimezone(datetime.UTC).isoformat()


def _fields(job: jobs.Job) -> dict[str, Any]:
    """Lays out a job as item attributes; unset fields are left out.

    Args:
        job: The job.

    Returns:
        The attributes, without the key.
    """
    optional = {
        "document_key": job.document_key,
        "content_hash": job.content_hash,
        "order": job.order,
        "lease_expires_at": (
            _time(job.lease_expires_at) if job.lease_expires_at else None
        ),
        "last_error_code": job.last_error_code,
        "last_error_message": job.last_error_message,
        "result_key": job.result_key,
    }
    return {
        "job_id": job.job_id,
        "kind": str(job.kind),
        "status": str(job.status),
        "input_key": job.input_key,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "created_at": _time(job.created_at),
        "updated_at": _time(job.updated_at),
        "names": [
            {"first_name": n.first_name, "last_name": n.last_name}
            for n in job.names
        ],
        **{name: v for name, v in optional.items() if v is not None},
    }


def _job(row: dict[str, Any]) -> jobs.Job:
    """Reads a job back from its item.

    Args:
        row: The decoded item.

    Returns:
        The job.
    """

    def text(name: str) -> str | None:
        return None if row.get(name) is None else str(row[name])

    def time(name: str) -> datetime.datetime | None:
        value = text(name)
        return datetime.datetime.fromisoformat(value) if value else None

    order = row.get("order")
    return jobs.Job(
        job_id=str(row["job_id"]),
        kind=jobs.JobKind(row["kind"]),
        status=jobs.JobStatus(row["status"]),
        input_key=str(row["input_key"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        created_at=datetime.datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.datetime.fromisoformat(str(row["updated_at"])),
        document_key=text("document_key"),
        content_hash=text("content_hash"),
        order=None if order is None else int(order),
        names=tuple(
            extraction.QueryName(str(n["first_name"]), str(n["last_name"]))
            for n in row.get("names", [])
        ),
        lease_expires_at=time("lease_expires_at"),
        last_error_code=text("last_error_code"),
        last_error_message=text("last_error_message"),
        result_key=text("result_key"),
    )
