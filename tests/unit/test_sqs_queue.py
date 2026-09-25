"""SQS settlement: dead letters are copied first, retries only hide."""

import boto3
from botocore import stub

from app.adapters.sqs_queue import queue as sqs_queue
from app.domain import jobs

WORK = "https://sqs.us-east-1.amazonaws.com/1/jobs"
DEAD = "https://sqs.us-east-1.amazonaws.com/1/jobs-dead"
BODY = '{"job_id": "job-1", "kind": "extract"}'


def stubbed() -> tuple[sqs_queue.SqsJobQueue, stub.Stubber, list[str]]:
    """Builds the queue on a stubbed client that records its calls.

    The stub serves one received message first.

    Returns:
        The queue, the stubber and the operations called, in order.
    """
    client = boto3.client(
        "sqs",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    called: list[str] = []
    client.meta.events.register(
        "provide-client-params.sqs.*",
        lambda model, **_: called.append(model.name),
    )
    stubber = stub.Stubber(client)
    stubber.add_response(
        "receive_message",
        {"Messages": [{"ReceiptHandle": "rh-1", "Body": BODY}]},
    )
    return sqs_queue.SqsJobQueue(client, WORK, DEAD, 0), stubber, called


async def test_dead_letter_copies_to_the_dlq_before_deleting() -> None:
    queue, stubber, called = stubbed()
    stubber.add_response(
        "send_message",
        {"MessageId": "m-2"},
        {"QueueUrl": DEAD, "MessageBody": BODY},
    )
    stubber.add_response(
        "delete_message", {}, {"QueueUrl": WORK, "ReceiptHandle": "rh-1"}
    )

    with stubber:
        delivery = await anext(queue.consume())
        await delivery.dead_letter()

    assert delivery.message == jobs.JobMessage("job-1", jobs.JobKind.EXTRACT)
    assert called == ["ReceiveMessage", "SendMessage", "DeleteMessage"]


async def test_retry_hides_the_message_for_the_delay_without_deleting() -> None:
    queue, stubber, called = stubbed()
    stubber.add_response(
        "change_message_visibility",
        {},
        {"QueueUrl": WORK, "ReceiptHandle": "rh-1", "VisibilityTimeout": 2},
    )

    with stubber:
        delivery = await anext(queue.consume())
        await delivery.retry(1.2)

    assert called == ["ReceiveMessage", "ChangeMessageVisibility"]
