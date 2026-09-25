"""Router for listing, reading and deleting indexed documents."""

from typing import Annotated
from typing import cast

import fastapi

from app.domain import errors
from app.domain import rag
from app.models import schemas
from app.ports import vector_store as vector_store_port

router = fastapi.APIRouter()


def store(request: fastapi.Request) -> vector_store_port.VectorStore:
    """Returns the vector store built at startup.

    Args:
        request: The current request.

    Returns:
        The vector store.
    """
    return cast(vector_store_port.VectorStore, request.app.state.vector_store)


Store = Annotated[vector_store_port.VectorStore, fastapi.Depends(store)]


def _response(record: rag.DocumentRecord) -> schemas.DocumentResponse:
    """Maps a stored document to its API shape.

    Args:
        record: The stored document.

    Returns:
        The response model.
    """
    return schemas.DocumentResponse(
        document_key=record.document_key,
        content_hash=record.content_hash,
        chunk_count=record.chunk_count,
    )


@router.get("/documents")
async def list_documents(
    documents: Store,
) -> list[schemas.DocumentResponse]:
    """Lists every indexed document.

    Args:
        documents: The vector store.

    Returns:
        One entry per document.
    """
    return [_response(record) for record in await documents.list_documents()]


@router.get("/documents/{document_key}")
async def get_document(
    document_key: str, documents: Store
) -> schemas.DocumentResponse:
    """Reads one indexed document.

    Args:
        document_key: Identity of the document.
        documents: The vector store.

    Returns:
        The document.

    Raises:
        errors.DocumentNotFoundError: If nothing is stored for the key.
    """
    record = await documents.get_document(document_key)
    if record is None:
        raise errors.DocumentNotFoundError(document_key)
    return _response(record)


@router.delete("/documents/{document_key}")
async def delete_document(
    document_key: str, documents: Store
) -> schemas.DeleteDocumentResponse:
    """Removes a document and all its chunks from the index.

    Args:
        document_key: Identity of the document.
        documents: The vector store.

    Returns:
        How many chunks were deleted.

    Raises:
        errors.DocumentNotFoundError: If nothing is stored for the key.
    """
    deleted = await documents.delete_document(document_key)
    if deleted == 0:
        raise errors.DocumentNotFoundError(document_key)
    return schemas.DeleteDocumentResponse(
        document_key=document_key, chunks_deleted=deleted
    )
