import csv
import shutil
from collections import Counter
from pathlib import Path

import pymupdf
import pytest

from app.services.bbox_service import boxes_for_spans, locate_names
from app.services.ocr_service import ocr_pages, page_text

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract not installed"
)

ROOT = Path(__file__).parents[2]
NAME = "Maria Gonzalez"


def scanned_pdf(font_size):
    """Image-only PDF of one line of text, plus the exact box of NAME in points."""
    with pymupdf.open() as source:
        page = source.new_page(width=612, height=792)
        page.insert_text(
            (72, 200),
            f"Signed by {NAME} today",
            fontname="helv",
            fontsize=font_size,
        )
        expected = tuple(page.search_for(NAME)[0])
        pixmap = page.get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
    with pymupdf.open() as scan:
        blank = scan.new_page(width=612, height=792)
        blank.insert_image(blank.rect, pixmap=pixmap)
        return scan.tobytes(deflate=True), expected


@pytest.mark.parametrize("font_size", [11, 14, 24])
def test_ac_box_04_box_matches_text_layer(font_size):
    pdf, (x0, y0, x1, y1) = scanned_pdf(font_size)

    text, words = page_text(ocr_pages(pdf)[0])

    assert NAME in text, f"OCR read {text!r}"
    start = text.index(NAME)
    box = boxes_for_spans(words, [(NAME, start, start + len(NAME))])[0]
    assert box["x"] >= x0 - 1 and box["x"] + box["width"] <= x1 + 1
    assert box["y"] >= y0 - 1 and box["y"] + box["height"] <= y1 + 1
    assert box["width"] >= 0.95 * (x1 - x0)


def read_gold(name):
    with (ROOT / "eval" / name).open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_ac_box_05_samples_match_gold():
    gold_names = Counter(
        (r["pdf"], int(r["page"]), r["name"]) for r in read_gold("gold_names.csv")
    )
    gold_boxes = read_gold("gold_boxes.csv")
    found = Counter()
    for pdf in sorted({pdf for pdf, _, _ in gold_names}):
        pages = ocr_pages((ROOT / "sample_pdfs" / pdf).read_bytes())
        for box in locate_names(pages):
            key = (pdf, box["page"], box["name"])
            found[key] += 1
            assert any(
                (r["pdf"], int(r["page"]), r["name"]) == key
                and all(
                    abs(float(r[k]) - box[k]) <= 2
                    for k in ("x", "y", "width", "height")
                )
                for r in gold_boxes
            ), f"box off gold: {key} {box}"

    hits = sum((found & gold_names).values())
    assert hits == sum(found.values()), "precision below 1.0"
    assert hits >= 54, f"recall {hits}/{sum(gold_names.values())}"
