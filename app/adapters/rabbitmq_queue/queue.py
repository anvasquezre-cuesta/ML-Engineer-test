"""Job queue on RabbitMQ quorum queues, with wait queues for backoff.

The work queue dead-letters to ``{queue}.dead`` once its delivery limit is
reached, which only happens when workers crash repeatedly. A retry is
published to ``{queue}.wait.{milliseconds}``, whose messages expire back
into the work queue.
"""

from collections.abc import AsyncIterator

from app.domain import jobs
from app.ports import job_queue


class RabbitMqJobQueue(job_queue.JobQueue):
    """Publishes and consumes job messages on one RabbitMQ work queue."""

    def __init__(
        self, url: str, queue: str, delivery_limit: int, prefetch: int
    ) -> None:
        """Initializes the queue; ``connect`` opens it.

        Args:
            url: AMQP URL, including credentials.
            queue: Name of the work queue.
            delivery_limit: Deliveries before the broker dead-letters a
                message whose worker never settled it.
            prefetch: Unacknowledged deliveries held at once.
        """
        self._url = url
        self._queue = queue
        self._delivery_limit = delivery_limit
        self._prefetch = prefetch

    async def connect(self) -> None:
        """Connects and declares the work and dead-letter queues.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def close(self) -> None:
        """Closes the connection; unsettled deliveries are redelivered.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def publish(self, message: jobs.JobMessage) -> None:
        """Publishes a persistent job message to the work queue.

        Args:
            message: The job message.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    def consume(self) -> AsyncIterator[job_queue.Delivery]:
        """Yields deliveries from the work queue until closed.

        Returns:
            The deliveries.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
