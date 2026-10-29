"""Dependency providers: hand the composition root's objects to routers (CONSTITUTION §4.5).

The ``Container`` is built once in the lifespan (``app/main.py``) and stored on
``app.state``; providers only read it — they never construct anything.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.upload import UploadLimits
from app.application.answer_question import AnswerQuestion
from app.application.extract_names import ExtractNames
from app.application.ingest_document import IngestDocument
from app.application.ports import PdfRasterizer


@dataclass(frozen=True)
class Container:
    """Everything the API layer needs, already wired by the composition root."""

    upload_limits: UploadLimits
    rasterizer: PdfRasterizer
    extract_names: ExtractNames
    ingest_document: IngestDocument
    answer_question: AnswerQuestion
    # Run by the lifespan at shutdown, e.g. to release the vector store's files.
    on_shutdown: tuple[Callable[[], None], ...] = ()


def get_container(request: Request) -> Container:
    """Return the container the lifespan stored on the app."""
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]
