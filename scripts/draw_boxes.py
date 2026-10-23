"""Draw OCR word boxes or detected-name boxes onto the PDF and save each page as a PNG.

The boxes are drawn with ``page.draw_rect`` in PDF points, the same coordinates
the API returns, so the images are visual proof that the boxes sit on the text.

    uv run python scripts/draw_boxes.py sample_pdfs/company_memo.pdf docs/images
    uv run python scripts/draw_boxes.py sample_pdfs/company_memo.pdf docs/images --layer names
"""

import argparse
from pathlib import Path

import pymupdf

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.spacy_ner import SpacyNER
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import get_settings
from app.domain.models import Box
from app.services.documents import DocumentLoader
from app.services.names import NameExtractor
from app.services.ocr import OcrService

RED = (0.85, 0.1, 0.1)
GREEN = (0.0, 0.6, 0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--layer", choices=("words", "names"), default="words")
    parser.add_argument("--preview-dpi", type=int, default=110)
    args = parser.parse_args()

    settings = get_settings()
    renderer = PyMuPDFRenderer()
    data = args.pdf.read_bytes()
    document = DocumentLoader(
        renderer, max_bytes=settings.limits.max_upload_bytes, max_pages=settings.limits.max_pages
    ).load(data)
    pages = OcrService(renderer, TesseractOCR(settings.ocr), dpi=settings.ocr.dpi).read(document)

    boxes: dict[int, list[Box]] = {page.index: [] for page in pages}
    if args.layer == "words":
        for ocr_page in pages:
            boxes[ocr_page.index] = [word.box for word in ocr_page.words]
        color, suffix = RED, "ocr_boxes"
    else:
        for mention in NameExtractor(SpacyNER(settings.ner)).extract(pages):
            boxes[mention.page].append(mention.box)
        color, suffix = GREEN, "name_boxes"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for index, page_boxes in boxes.items():
            page = pdf[index]
            for box in page_boxes:
                page.draw_rect(pymupdf.Rect(box.x0, box.y0, box.x1, box.y1), color=color, width=1)
            out = args.out_dir / f"{args.pdf.stem}_p{index}_{suffix}.png"
            page.get_pixmap(dpi=args.preview_dpi).save(out)
            print(f"{out}  ({len(page_boxes)} boxes)")


if __name__ == "__main__":
    main()
