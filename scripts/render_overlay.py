"""Renders ground-truth boxes over the sample PDFs for visual review.

Boxes are drawn with PyMuPDF in page coordinates (points, top-left origin),
so a box that sits on its name also confirms the coordinate convention.
"""

import argparse
import json
from pathlib import Path

import pymupdf

DATA_DIR = Path(__file__).parents[1] / "tests" / "data" / "ground_truth"
PDF_DIR = Path(__file__).parents[1] / "sample_pdfs"
RED = (1.0, 0.0, 0.0)


def render(truth_file: Path, out_dir: Path, dpi: int) -> list[Path]:
    """Draws the boxes of one ground-truth file and saves one PNG per page.

    Args:
        truth_file: Ground-truth JSON produced by ``draft_ground_truth.py``.
        out_dir: Directory for the PNG files.
        dpi: Output resolution.

    Returns:
        The written image paths.
    """
    truth = json.loads(truth_file.read_text())
    written = []
    with pymupdf.open(PDF_DIR / truth["document"]) as document:
        for entry in truth["names"]:
            page = document[entry["page_number"]]
            rect = pymupdf.Rect(
                entry["x"],
                entry["y"],
                entry["x"] + entry["width"],
                entry["y"] + entry["height"],
            )
            page.draw_rect(rect, color=RED, width=1)
            page.insert_text(
                (rect.x0, rect.y0 - 2), entry["name"], fontsize=6, color=RED
            )
        for page in document:
            target = out_dir / f"{truth_file.stem}-p{page.number}.png"
            page.get_pixmap(dpi=dpi).save(target)
            written.append(target)
    return written


def main() -> None:
    """Renders every ground-truth file found next to ``names.json``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--dpi", type=int, default=100)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for truth_file in sorted(DATA_DIR.glob("*.json")):
        if truth_file.name == "names.json":
            continue
        for path in render(truth_file, args.out_dir, args.dpi):
            print(path)


if __name__ == "__main__":
    main()
