"""RabbitMQ job queue: settlement, delayed retries, dead letters, crashes."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import uuid

import aio_pika
import pytest

from app.adapters.rabbitmq_queue import queue as rabbitmq_queue
from app.domain import jobs
from app.ports import job_queue

pytestmark = [pytest.mark.integration, pytest.mark.docker]

URL = "amqp://guest:guest@localhost:5672/"
MESSAGE = jobs.JobMessage("job-1", jobs.JobKind.EXTRACT)


@contextlib.asynccontextmanager
async def opened(name: str) -> AsyncIterator[rabbitmq_queue.RabbitMqJobQueue]:
    """Opens the adapter on the work queue ``name``.

    Args:
        name: Work queue name.

    Yields:
        The connected queue.
    """
    queue = rabbitmq_queue.RabbitMqJobQueue(URL, name, 5, 1)
    await queue.connect()
    try:
        yield queue
    finally:
        await queue.close()


async def next_delivery(
    queue: rabbitmq_queue.RabbitMqJobQueue, within_s: float
) -> job_queue.Delivery | None:
    """Waits for the next delivery.

    Args:
        queue: The queue.
        within_s: How long to wait.

    Returns:
        The delivery, or ``None`` if none arrived in time.
    """
    deliveries = queue.consume()
    try:
        return await asyncio.wait_for(anext(deliveries), within_s)
    except TimeoutError:
        return None


async def dead_lettered(name: str) -> list[str]:
    """Drains the dead-letter queue of work queue ``name``.

    Args:
        name: Work queue name.

    Returns:
        The message bodies.
    """
    connection = await aio_pika.connect(URL)
    async with connection:
        channel = await connection.channel()
        dead = await channel.get_queue(f"{name}.dead")
        bodies = []
        while (message := await dead.get(fail=False)) is not None:
            await message.ack()
            bodies.append(message.body.decode())
        return bodies


def unique() -> str:
    """Returns a work queue name no other test uses.

    Returns:
        The name.
    """
    return f"test.jobs.{uuid.uuid4().hex}"


async def test_ack_removes_the_job_for_every_worker() -> None:
    name = unique()
    async with opened(name) as queue:
        await queue.publish(MESSAGE)
        delivery = await next_delivery(queue, 5)
        assert delivery is not None and delivery.message == MESSAGE
        await delivery.ack()

    async with opened(name) as next_worker:
        again = await next_delivery(next_worker, 1)

    assert again is None


async def test_retry_is_redelivered_only_after_its_delay() -> None:
    name = unique()
    async with opened(name) as queue:
        await queue.publish(MESSAGE)
        delivery = await next_delivery(queue, 5)
        assert delivery is not None
        await delivery.retry(1.5)

        early = await next_delivery(queue, 0.7)
        later = await next_delivery(queue, 5)

    assert early is None
    assert later is not None and later.message == MESSAGE


async def test_dead_letter_moves_the_job_to_the_dead_letter_queue() -> None:
    name = unique()
    async with opened(name) as queue:
        await queue.publish(MESSAGE)
        delivery = await next_delivery(queue, 5)
        assert delivery is not None
        await delivery.dead_letter()

    async with opened(name) as next_worker:
        again = await next_delivery(next_worker, 1)

    assert again is None
    assert len(await dead_lettered(name)) == 1


async def test_unsettled_job_is_redelivered_after_a_worker_crash() -> None:
    name = unique()
    async with opened(name) as crashed:
        await crashed.publish(MESSAGE)
        assert await next_delivery(crashed, 5) is not None

    async with opened(name) as survivor:
        redelivered = await next_delivery(survivor, 5)

    assert redelivered is not None and redelivered.message == MESSAGE
