"""Freezes the service's OCR text of the sample PDFs for the retrieval gate.

The retrieval gate reads this file instead of running Tesseract, so an OCR
upgrade cannot change retrieval metrics. Rerun it only on purpose, and
review the diff before committing.
"""

import json
import pathlib

from app import config
from app.adapters.pymupdf import page_renderer
from app.adapters.tesseract import ocr
from app.domain import page_text

REPO = pathlib.Path(__file__).parents[1]
OUT = REPO / "tests" / "data" / "rag_eval" / "ocr_pages.json"
DOCUMENTS = ("company_memo.pdf", "meeting_minutes.pdf", "research_report.pdf")


def main() -> None:
    """Runs the service's renderer and OCR and writes the page texts."""
    settings = config.Settings()
    renderer = page_renderer.PyMuPdfRenderer(settings.render.dpi)
    reader = ocr.TesseractOcr(settings.ocr.languages, settings.ocr.timeout_s)
    pages = [
        {
            "document": name,
            "page": page.page_number,
            "text": page_text.build_page_text(reader.read(page)).text,
        }
        for name in DOCUMENTS
        for page in renderer.render((REPO / "sample_pdfs" / name).read_bytes())
    ]
    OUT.write_text(json.dumps({"pages": pages}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
