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


def document_id(document_key: str) -> str:
    """Returns the store id of a document key.

    Store keys hold this id instead of the key, which may be a filename.

    Args:
        document_key: The document key.

    Returns:
        The id as a canonical UUID string.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError


def occurrence_id(
    document_key: str,
    content_hash: str,
    generation: str,
    page_number: int,
    ordinal: int,
) -> str:
    """Returns the id of one stored name occurrence.

    The id is a UUIDv5 of the document, its content, the extraction run, the
    page and the position in the run, so a retried write overwrites the same
    item and equal content under two keys never shares an id.

    Args:
        document_key: The document key.
        content_hash: SHA-256 of the document content.
        generation: The extraction run.
        page_number: 0-based page index.
        ordinal: Position of the occurrence in the run.

    Returns:
        The id as a canonical UUID string.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError
