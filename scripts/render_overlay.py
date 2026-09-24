"""Renders ground-truth boxes over the sample PDFs for visual review.

Boxes are stored in points with the top-left origin of the displayed page
and drawn through the page's derotation, so a box that sits on its name also
confirms the coordinate convention on rotated pages.
"""

import argparse
import json
from pathlib import Path

import pymupdf

DATA_DIR = Path(__file__).parents[1] / "tests" / "data" / "ground_truth"
PDF_DIR = Path(__file__).parents[1] / "sample_pdfs"
RED = (1.0, 0.0, 0.0)


def render(
    truth_file: Path, pdf_dir: Path, out_dir: Path, dpi: int
) -> list[Path]:
    """Draws the boxes of one ground-truth file and saves one PNG per page.

    Args:
        truth_file: Ground-truth JSON with boxes per name occurrence.
        pdf_dir: Directory holding the PDF the ground truth refers to.
        out_dir: Directory for the PNG files.
        dpi: Output resolution.

    Returns:
        The written image paths.
    """
    truth = json.loads(truth_file.read_text())
    written = []
    with pymupdf.open(pdf_dir / truth["document"]) as document:
        for entry in truth["names"]:
            page = document[entry["page_number"]]
            rect = pymupdf.Rect(
                entry["x"],
                entry["y"],
                entry["x"] + entry["width"],
                entry["y"] + entry["height"],
            )
            label = pymupdf.Point(rect.x0, rect.y0 - 2)
            page.draw_rect(rect * page.derotation_matrix, color=RED, width=1)
            page.insert_text(
                label * page.derotation_matrix,
                entry["name"],
                fontsize=6,
                color=RED,
                rotate=page.rotation,
            )
        for page in document:
            target = out_dir / f"{truth_file.stem}-p{page.number}.png"
            page.get_pixmap(dpi=dpi).save(target)
            written.append(target)
    return written


def main() -> None:
    """Renders every ground-truth file in the truth directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--truth-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--pdf-dir", type=Path, default=PDF_DIR)
    parser.add_argument("--dpi", type=int, default=100)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for truth_file in sorted(args.truth_dir.glob("*.json")):
        if truth_file.name == "names.json":
            continue
        for path in render(truth_file, args.pdf_dir, args.out_dir, args.dpi):
            print(path)


if __name__ == "__main__":
    main()
