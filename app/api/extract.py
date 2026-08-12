"""`POST /api/extract` — implement the extraction endpoint here.

Wire OCR -> NER -> bounding boxes -> fuzzy matching and return an
``ExtractionResponse``. Keep this router thin: validate input, delegate to
services, map domain errors to HTTP status codes. Do the real work in the
service layer so it is testable without HTTP.
"""

from fastapi import APIRouter

router = APIRouter()

# TODO: implement POST /api/extract (response_model=ExtractionResponse)
