"""Job queue on RabbitMQ quorum queues, with wait queues for backoff.

The work queue dead-letters to ``{queue}.dead`` once its delivery limit is
reached, which only happens when workers crash repeatedly. A retry is
published to ``{queue}.wait.{milliseconds}``, whose messages expire back
into the work queue.
"""

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

import aio_pika
from aio_pika import abc as pika_abc
import aiormq

from app.domain import errors
from app.domain import jobs
from app.ports import job_queue

_FAILURES = (aio_pika.exceptions.AMQPError, aiormq.AMQPError, OSError)


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
        self._connection: pika_abc.AbstractRobustConnection | None = None
        self._channel: pika_abc.AbstractChannel | None = None
        self._work: pika_abc.AbstractQueue | None = None
        self._inbox: asyncio.Queue[pika_abc.AbstractIncomingMessage] = (
            asyncio.Queue()
        )
        self._consumer_tag: str | None = None
        self._wait_queues: set[str] = set()

    async def connect(self) -> None:
        """Connects and declares the work and dead-letter queues.

        Raises:
            errors.JobQueueUnavailableError: If the broker is unreachable.
        """
        try:
            self._connection = await aio_pika.connect_robust(self._url)
            self._channel = await self._connection.channel()
            await self._channel.set_qos(prefetch_count=self._prefetch)
            await self._channel.declare_queue(
                self.dead_letter_queue,
                durable=True,
                arguments={"x-queue-type": "quorum"},
            )
            self._work = await self._channel.declare_queue(
                self._queue,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-delivery-limit": self._delivery_limit,
                    "x-dead-letter-exchange": "",
                    "x-dead-letter-routing-key": self.dead_letter_queue,
                },
            )
        except _FAILURES as exc:
            raise errors.JobQueueUnavailableError() from exc

    @property
    def dead_letter_queue(self) -> str:
        """Returns the name of the dead-letter queue.

        Returns:
            ``{queue}.dead``.
        """
        return f"{self._queue}.dead"

    async def close(self) -> None:
        """Closes the connection; unsettled deliveries are redelivered."""
        if self._connection is not None:
            await self._connection.close()

    async def publish(self, message: jobs.JobMessage) -> None:
        """Publishes a persistent job message to the work queue.

        Args:
            message: The job message.
        """
        await self._send(self._queue, _encode(message))

    async def consume(self) -> AsyncIterator[job_queue.Delivery]:
        """Yields deliveries from the work queue until closed.

        Every call reads one shared consumer's inbox, so a caller that
        stops waiting never loses or holds back a delivery.

        Yields:
            The deliveries.

        Raises:
            errors.JobQueueUnavailableError: If the consumer cannot start.
        """
        if self._consumer_tag is None:
            try:
                self._consumer_tag = await self._opened().consume(
                    self._inbox.put
                )
            except _FAILURES as exc:
                raise errors.JobQueueUnavailableError() from exc
        while True:
            yield RabbitMqDelivery(self, await self._inbox.get())

    async def send_after(self, body: bytes, delay_s: float) -> None:
        """Publishes ``body`` to expire back into the work queue later.

        Args:
            body: The message body.
            delay_s: Delay before it is redelivered.

        Raises:
            errors.JobQueueUnavailableError: If the broker fails.
        """
        delay_ms = max(1, round(delay_s * 1000))
        name = f"{self._queue}.wait.{delay_ms}"
        if name not in self._wait_queues:
            try:
                await self._opened_channel().declare_queue(
                    name,
                    durable=True,
                    arguments={
                        "x-message-ttl": delay_ms,
                        "x-dead-letter-exchange": "",
                        "x-dead-letter-routing-key": self._queue,
                    },
                )
            except _FAILURES as exc:
                raise errors.JobQueueUnavailableError() from exc
            self._wait_queues.add(name)
        await self._send(name, body)

    async def send_dead(self, body: bytes) -> None:
        """Publishes ``body`` to the dead-letter queue.

        Args:
            body: The message body.
        """
        await self._send(self.dead_letter_queue, body)

    async def _send(self, routing_key: str, body: bytes) -> None:
        """Publishes a persistent message through the default exchange.

        Args:
            routing_key: Destination queue.
            body: The message body.

        Raises:
            errors.JobQueueUnavailableError: If the broker fails.
        """
        message = aio_pika.Message(
            body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        try:
            exchange = self._opened_channel().default_exchange
            await exchange.publish(message, routing_key=routing_key)
        except _FAILURES as exc:
            raise errors.JobQueueUnavailableError() from exc

    def _opened(self) -> pika_abc.AbstractQueue:
        """Returns the declared work queue.

        Returns:
            The work queue.

        Raises:
            errors.JobQueueUnavailableError: If ``connect`` was not called.
        """
        if self._work is None:
            raise errors.JobQueueUnavailableError("The queue is not open.")
        return self._work

    def _opened_channel(self) -> pika_abc.AbstractChannel:
        """Returns the open channel.

        Returns:
            The channel.

        Raises:
            errors.JobQueueUnavailableError: If ``connect`` was not called.
        """
        if self._channel is None:
            raise errors.JobQueueUnavailableError("The queue is not open.")
        return self._channel


class RabbitMqDelivery(job_queue.Delivery):
    """One received job message, settled on the work queue."""

    def __init__(
        self,
        queue: RabbitMqJobQueue,
        incoming: pika_abc.AbstractIncomingMessage,
    ) -> None:
        """Initializes the delivery.

        Args:
            queue: The queue it came from.
            incoming: The broker message.
        """
        self._queue = queue
        self._incoming = incoming
        self.message = _decode(incoming.body)

    async def ack(self) -> None:
        """Removes the message from the work queue."""
        await self._settle(self._incoming.ack)

    async def retry(self, delay_s: float) -> None:
        """Parks a copy in a wait queue, then removes the original.

        Args:
            delay_s: Backoff before the next delivery.
        """
        await self._queue.send_after(self._incoming.body, delay_s)
        await self._settle(self._incoming.ack)

    async def dead_letter(self) -> None:
        """Publishes a copy to the dead-letter queue, then removes it."""
        await self._queue.send_dead(self._incoming.body)
        await self._settle(self._incoming.ack)

    async def _settle(self, settle: Any) -> None:
        """Settles the broker message.

        Args:
            settle: The broker settlement coroutine function.

        Raises:
            errors.JobQueueUnavailableError: If the broker fails.
        """
        try:
            await settle()
        except _FAILURES as exc:
            raise errors.JobQueueUnavailableError() from exc


def _encode(message: jobs.JobMessage) -> bytes:
    """Serializes a job message.

    Args:
        message: The job message.

    Returns:
        JSON bytes.
    """
    payload = {"job_id": message.job_id, "kind": str(message.kind)}
    return json.dumps(payload).encode()


def _decode(body: bytes) -> jobs.JobMessage:
    """Reads a job message.

    Args:
        body: JSON bytes.

    Returns:
        The job message.
    """
    payload = json.loads(body)
    kind = jobs.JobKind(payload["kind"])
    return jobs.JobMessage(str(payload["job_id"]), kind)
