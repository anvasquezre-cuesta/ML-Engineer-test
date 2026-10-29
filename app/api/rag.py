"""RAG endpoints — thin driving adapters: parse, call the use case, map (ADR-012).

Sync ``def`` on purpose: OCR and embedding are CPU-bound, so FastAPI runs them in its
threadpool instead of blocking the event loop (TRD §8).
"""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.dependencies import ContainerDep
from app.api.mapping import to_ingest_response, to_rag_response
from app.api.upload import read_pdf_upload
from app.models.schemas import IngestResponse, RAGRequest, RAGResponse

router = APIRouter()

INGEST_DESCRIPTION = """Upload a scanned PDF (`pdf_file`) to index it for `/api/ask`.

The file is validated exactly like `/api/extract`. Every page is OCR'd, cut into
word-safe chunks of whole paragraphs/sentences, embedded and stored. Chunk ids start
with a hash of the PDF's content: a different document never overwrites another, and
uploading the same PDF again replaces its own chunks instead of duplicating them.
`chunks_stored` is the number of chunks now stored for this document."""


@router.post("/ingest", response_model=IngestResponse, description=INGEST_DESCRIPTION)
def ingest(
    container: ContainerDep,
    pdf_file: Annotated[UploadFile | None, File()] = None,
) -> IngestResponse:
    """Index a scanned PDF for question answering."""
    pdf = read_pdf_upload(pdf_file, container.upload_limits, container.rasterizer)
    file_name = pdf_file.filename if pdf_file is not None else None
    return to_ingest_response(container.ingest_document.execute(pdf, file_name))


ASK_DESCRIPTION = """Ask a question about the ingested documents (`{"question": "..."}`).

The question is matched against the stored chunks by meaning and by exact words, the
candidates are reranked, and the best few are sent to the LLM as numbered passages.
`sources` lists `"<file>, page <n>"` (0-based page) for the passages the answer cites;
they are built by the service, never by the LLM, so they always exist. When nothing
relevant is found — or the answer cites nothing — `answer` is "The answer is not in the
ingested documents." and `sources` is empty."""


@router.post("/ask", response_model=RAGResponse, description=ASK_DESCRIPTION)
def ask(container: ContainerDep, request: RAGRequest) -> RAGResponse:
    """Answer a question grounded in the ingested documents."""
    return to_rag_response(container.answer_question.execute(request.question))
