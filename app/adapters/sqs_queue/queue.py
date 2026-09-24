"""Job queue on SQS; backoff hides a message, dead letters are copied.

The queue's redrive policy moves a message to the dead-letter queue after
repeated unsettled receives, the backstop for crashed workers.
"""

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Callable
import functools
import math
from typing import Any

import boto3
from botocore import config as botocore_config
from botocore import exceptions

from app import config
from app.domain import errors
from app.domain import jobs
from app.ports import job_queue

MAX_VISIBILITY_S = 43_200


def build_client(settings: config.QueueSettings) -> Any:
    """Builds an SQS client; credentials come from the task role.

    Args:
        settings: Region of the queues.

    Returns:
        The boto3 SQS client.
    """
    return boto3.client(
        "sqs",
        region_name=settings.sqs_region,
        config=botocore_config.Config(
            retries={"total_max_attempts": 4, "mode": "standard"},
        ),
    )


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
        """
        await self.call(
            self._client.send_message,
            QueueUrl=self._queue_url,
            MessageBody=jobs.encode_message(message),
        )

    async def consume(self) -> AsyncIterator[job_queue.Delivery]:
        """Long-polls the work queue and yields each message.

        Yields:
            The deliveries.
        """
        while True:
            response = await self.call(
                self._client.receive_message,
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=self._wait_s,
            )
            for received in response.get("Messages", []):
                yield SqsDelivery(self, received)

    async def delete(self, receipt_handle: str) -> None:
        """Deletes a received message.

        Args:
            receipt_handle: The message's receipt handle.
        """
        await self.call(
            self._client.delete_message,
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt_handle,
        )

    async def hide(self, receipt_handle: str, delay_s: float) -> None:
        """Makes a received message visible again after ``delay_s``.

        Args:
            receipt_handle: The message's receipt handle.
            delay_s: Delay, rounded up to whole seconds, at most 12 hours.
        """
        await self.call(
            self._client.change_message_visibility,
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=min(math.ceil(delay_s), MAX_VISIBILITY_S),
        )

    async def send_dead(self, body: str) -> None:
        """Sends a copy of a message body to the dead-letter queue.

        Args:
            body: The message body.
        """
        await self.call(
            self._client.send_message,
            QueueUrl=self._dead_letter_url,
            MessageBody=body,
        )

    async def call(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Runs a blocking client call off the event loop.

        Args:
            method: The boto3 client method.
            **kwargs: Its parameters.

        Returns:
            The response.

        Raises:
            errors.JobQueueUnavailableError: If the call fails.
        """
        try:
            return await asyncio.to_thread(functools.partial(method, **kwargs))
        except (exceptions.BotoCoreError, exceptions.ClientError) as exc:
            raise errors.JobQueueUnavailableError() from exc


class SqsDelivery(job_queue.Delivery):
    """One received SQS message and its receipt handle."""

    def __init__(self, queue: SqsJobQueue, received: dict[str, Any]) -> None:
        """Initializes the delivery.

        Args:
            queue: The queue it came from.
            received: The message as returned by ``ReceiveMessage``.
        """
        self._queue = queue
        self._handle = str(received["ReceiptHandle"])
        self._body = str(received["Body"])
        self.message = jobs.decode_message(self._body)

    async def ack(self) -> None:
        """Deletes the message."""
        await self._queue.delete(self._handle)

    async def retry(self, delay_s: float) -> None:
        """Hides the message until the backoff has passed.

        Args:
            delay_s: Backoff before the next delivery.
        """
        await self._queue.hide(self._handle, delay_s)

    async def dead_letter(self) -> None:
        """Copies the message to the dead-letter queue, then deletes it.

        The copy is sent first, so a failure never loses the job.
        """
        await self._queue.send_dead(self._body)
        await self._queue.delete(self._handle)
