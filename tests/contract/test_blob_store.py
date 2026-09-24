"""The fake and the S3 adapter on SeaweedFS honour the same blob contract."""

import uuid

import pydantic
import pytest

from app import config
from app.adapters.s3_blobs import store as s3_store
from app.domain import errors
from app.ports import blob_store
from tests.fakes import jobs as job_fakes

LOCAL = config.BlobSettings(
    endpoint_url="http://localhost:8333",
    access_key_id=pydantic.SecretStr("docintel-local"),
    secret_access_key=pydantic.SecretStr("docintel-local-secret"),
)


def store_of(kind: str) -> blob_store.BlobStore:
    """Returns the fake, or the S3 adapter on the compose SeaweedFS.

    Args:
        kind: ``fake`` or ``s3``.

    Returns:
        The blob store.
    """
    if kind == "fake":
        return job_fakes.InMemoryBlobStore()
    return s3_store.S3BlobStore(s3_store.build_client(LOCAL), LOCAL.bucket)


@pytest.mark.parametrize(
    "kind",
    ["fake", pytest.param("s3", marks=pytest.mark.docker)],
)
async def test_objects_round_trip_and_a_missing_one_reads_as_none(
    kind: str,
) -> None:
    store = store_of(kind)
    key = f"inputs/{uuid.uuid4().hex}.pdf"
    pdf = b"%PDF-1.7\n\x00\xff binary"

    await store.put(key, pdf)
    read = await store.get(key)
    await store.delete(key)
    await store.delete(key)
    after = await store.get(key)

    assert (read, after) == (pdf, None)


@pytest.mark.docker
async def test_rejected_credentials_fail_rather_than_read_as_missing() -> None:
    wrong = LOCAL.model_copy(
        update={"access_key_id": pydantic.SecretStr("wrong")}
    )
    store = s3_store.S3BlobStore(s3_store.build_client(wrong), LOCAL.bucket)

    with pytest.raises(errors.BlobStoreUnavailableError):
        await store.get("inputs/anything.pdf")
