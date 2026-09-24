"""Deterministic identifiers for stored chunks."""

import json
import uuid

from app.domain import rag

ID_PREFIX = "docintel:chunk"


def chunk_point_id(chunk: rag.Chunk) -> str:
    """Returns the vector-store id of ``chunk``.

    The id is a UUIDv5 of the document key, content hash, page and chunk
    index, so re-ingesting identical content overwrites the same points and
    chunks of different documents never share an id. The prefix keeps these
    ids apart from other UUIDv5 names in the standard URL namespace.

    Args:
        chunk: The chunk to identify.

    Returns:
        The id as a canonical UUID string.
    """
    key = json.dumps(
        [
            ID_PREFIX,
            chunk.document_key,
            chunk.content_hash,
            chunk.page_number,
            chunk.chunk_index,
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))
