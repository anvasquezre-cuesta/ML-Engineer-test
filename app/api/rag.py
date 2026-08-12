"""RAG endpoints — implement `POST /api/ingest` and `POST /api/ask` here.

Keep the router thin; delegate to the RAG / vector / OCR services. Map failures
(bad upload, vector store down, LLM error) to meaningful HTTP status codes.
"""

from fastapi import APIRouter

router = APIRouter()

# TODO: implement POST /api/ingest (response_model=IngestResponse)
# TODO: implement POST /api/ask    (response_model=RAGResponse)
