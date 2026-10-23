"""Draw every OCR word box onto the PDF and save each page as a PNG.

The boxes are drawn with ``page.draw_rect`` in PDF points, the same coordinates
the API returns, so the image is visual proof that the pixel -> point
conversion is right.

    uv run python scripts/draw_ocr_boxes.py sample_pdfs/company_memo.pdf docs/images
"""

import argparse
from pathlib import Path

import pymupdf

from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import get_settings
from app.services.documents import DocumentLoader
from app.services.ocr import OcrService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--preview-dpi", type=int, default=110)
    args = parser.parse_args()

    settings = get_settings()
    renderer = PyMuPDFRenderer()
    data = args.pdf.read_bytes()
    document = DocumentLoader(
        renderer, max_bytes=settings.limits.max_upload_bytes, max_pages=settings.limits.max_pages
    ).load(data)
    pages = OcrService(renderer, TesseractOCR(settings.ocr), dpi=settings.ocr.dpi).read(document)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for ocr_page in pages:
            page = pdf[ocr_page.index]
            for word in ocr_page.words:
                rect = pymupdf.Rect(word.box.x0, word.box.y0, word.box.x1, word.box.y1)
                page.draw_rect(rect, color=(0.85, 0.1, 0.1), width=0.6)
            out = args.out_dir / f"{args.pdf.stem}_p{ocr_page.index}_ocr_boxes.png"
            page.get_pixmap(dpi=args.preview_dpi).save(out)
            print(f"{out}  ({len(ocr_page.words)} words)")


if __name__ == "__main__":
    main()
