"""Drafts ground-truth name boxes for the sample PDFs from a Tesseract pass.

The names per document are curated by hand in ``names.json``; this script
only locates every occurrence of each name among the OCR words, independent
of the service pipeline. The output must be checked with
``render_overlay.py`` before it is used as a test oracle.
"""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import unicodedata

from PIL import Image
import pymupdf
import pytesseract

DATA_DIR = Path(__file__).parents[1] / "tests" / "data" / "ground_truth"
PDF_DIR = Path(__file__).parents[1] / "sample_pdfs"
STRIP_CHARS = ".,;:()\"'’‘"


@dataclass(frozen=True)
class Word:
    """An OCR word with its box in top-left PDF points.

    Attributes:
        key: Normalized text used for matching.
        x0: Left edge.
        y0: Top edge.
        x1: Right edge.
        y1: Bottom edge.
    """

    key: str
    x0: float
    y0: float
    x1: float
    y1: float


def normalize(token: str) -> str:
    """Casefolds, strips accents and surrounding punctuation from a token.

    Args:
        token: Raw token.

    Returns:
        The normalized token.
    """
    decomposed = unicodedata.normalize("NFKD", token.replace("’", "'"))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return plain.casefold().strip(STRIP_CHARS)


def read_words(page: pymupdf.Page, dpi: int) -> list[Word]:
    """Renders a page and returns its OCR words in reading order.

    Args:
        page: The PDF page.
        dpi: Render resolution.

    Returns:
        The recognized words with boxes in points.
    """
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    sx = page.rect.width / pix.width
    sy = page.rect.height / pix.height
    words = []
    for i, text in enumerate(data["text"]):
        if float(data["conf"][i]) < 0 or not text.strip():
            continue
        left, top = data["left"][i], data["top"][i]
        words.append(
            Word(
                key=normalize(text),
                x0=left * sx,
                y0=top * sy,
                x1=(left + data["width"][i]) * sx,
                y1=(top + data["height"][i]) * sy,
            )
        )
    return words


def find_occurrences(words: list[Word], name: str) -> list[dict[str, float]]:
    """Finds every run of consecutive words that spells ``name``.

    Args:
        words: The page words in reading order.
        name: The curated name.

    Returns:
        One box per occurrence, as ``x``, ``y``, ``width``, ``height``.
    """
    target = [normalize(token) for token in name.split()]
    boxes = []
    for start in range(len(words) - len(target) + 1):
        run = words[start : start + len(target)]
        if [word.key for word in run] == target:
            x0 = min(word.x0 for word in run)
            y0 = min(word.y0 for word in run)
            x1 = max(word.x1 for word in run)
            y1 = max(word.y1 for word in run)
            boxes.append(
                {
                    "x": round(x0, 2),
                    "y": round(y0, 2),
                    "width": round(x1 - x0, 2),
                    "height": round(y1 - y0, 2),
                }
            )
    return boxes


def draft(pdf_name: str, names: list[str], dpi: int) -> dict[str, object]:
    """Builds the ground-truth document for one PDF.

    Args:
        pdf_name: File name inside ``sample_pdfs``.
        names: Curated names for the document.
        dpi: Render resolution.

    Returns:
        The ground truth as a JSON-serializable dict.
    """
    entries = []
    with pymupdf.open(PDF_DIR / pdf_name) as document:
        for page in document:
            words = read_words(page, dpi)
            for name in names:
                for box in find_occurrences(words, name):
                    entries.append(
                        {"name": name, "page_number": page.number, **box}
                    )
        page_count = document.page_count
    missing = sorted({*names} - {str(entry["name"]) for entry in entries})
    if missing:
        print(f"{pdf_name}: no occurrence found for {missing}")
    print(f"{pdf_name}: {len(entries)} occurrences")
    return {"document": pdf_name, "page_count": page_count, "names": entries}


def main() -> None:
    """Writes one ground-truth JSON file per curated PDF."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    curated = json.loads((DATA_DIR / "names.json").read_text())
    for pdf_name, names in curated.items():
        truth = draft(pdf_name, names, args.dpi)
        target = DATA_DIR / f"{Path(pdf_name).stem}.json"
        target.write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    main()
