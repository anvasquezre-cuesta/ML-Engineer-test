"""Router for listing, reading and deleting indexed documents."""

from typing import Annotated
from typing import cast

import fastapi

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


@router.get("/documents")
async def list_documents(  # noqa: DOC501, DOC503
    documents: Store,
) -> list[schemas.DocumentResponse]:
    """Lists every indexed document.

    Args:
        documents: The vector store.

    Returns:
        One entry per document.
    """
    raise NotImplementedError


@router.get("/documents/{document_key}")
async def get_document(  # noqa: DOC501, DOC503
    document_key: str, documents: Store
) -> schemas.DocumentResponse:
    """Reads one indexed document.

    Args:
        document_key: Identity of the document.
        documents: The vector store.

    Returns:
        The document.
    """
    raise NotImplementedError


@router.delete("/documents/{document_key}")
async def delete_document(  # noqa: DOC501, DOC503
    document_key: str, documents: Store
) -> schemas.DeleteDocumentResponse:
    """Removes a document and all its chunks from the index.

    Args:
        document_key: Identity of the document.
        documents: The vector store.

    Returns:
        How many chunks were deleted.
    """
    raise NotImplementedError
