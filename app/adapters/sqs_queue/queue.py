"""Job queue on SQS; backoff hides a message, dead letters are copied.

The queue's redrive policy moves a message to the dead-letter queue after
repeated unsettled receives, the backstop for crashed workers.
"""

from collections.abc import AsyncIterator
from typing import Any

from app.domain import jobs
from app.ports import job_queue


class SqsJobQueue(job_queue.JobQueue):
    """Publishes and long-polls job messages on one SQS queue."""

    def __init__(
        self, client: Any, queue_url: str, dead_letter_url: str, wait_s: int
    ) -> None:
        """Initializes the queue.

        Args:
            client: The boto3 SQS client.
            queue_url: URL of the work queue.
            dead_letter_url: URL of the dead-letter queue.
            wait_s: Long-poll wait of each receive, in seconds.
        """
        self._client = client
        self._queue_url = queue_url
        self._dead_letter_url = dead_letter_url
        self._wait_s = wait_s

    async def publish(self, message: jobs.JobMessage) -> None:
        """Sends a job message to the work queue.

        Args:
            message: The job message.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    def consume(self) -> AsyncIterator[job_queue.Delivery]:
        """Long-polls the work queue and yields each message.

        Returns:
            The deliveries.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
