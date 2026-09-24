"""Port for delivering jobs to workers."""

import abc
from collections.abc import AsyncIterator

from app.domain import jobs


class Delivery(abc.ABC):
    """One received job message and the ways to settle it.

    Attributes:
        message: The job message.
    """

    message: jobs.JobMessage

    @abc.abstractmethod
    async def ack(self) -> None:
        """Removes the message from the queue after the job finished."""

    @abc.abstractmethod
    async def retry(self, delay_s: float) -> None:
        """Makes the message available again after ``delay_s`` seconds.

        Args:
            delay_s: Backoff before the next delivery.
        """

    @abc.abstractmethod
    async def dead_letter(self) -> None:
        """Moves the message to the dead-letter queue."""


class JobQueue(abc.ABC):
    """Job queue with delayed retries and a dead-letter queue.

    Every method may raise ``JobQueueUnavailableError``.
    """

    @abc.abstractmethod
    async def publish(self, message: jobs.JobMessage) -> None:
        """Enqueues a job for a worker.

        Args:
            message: The job message.
        """

    @abc.abstractmethod
    def consume(self) -> AsyncIterator[Delivery]:
        """Yields deliveries one at a time until the consumer is closed.

        Returns:
            An async iterator of deliveries.
        """
