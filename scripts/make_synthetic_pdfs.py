"""Generates synthetic PDFs whose name boxes are known from their layout.

Each case targets an extraction edge case the sample PDFs do not cover:
accented names, two names on one line and an upright page stored with a
``/Rotate`` of 90 degrees. Boxes are written in the same format as the
curated ground truth: points, top-left origin of the displayed page.
"""

import argparse
import dataclasses
import json
import pathlib

import pymupdf

OUT_DIR = pathlib.Path(__file__).parents[1] / "tests" / "data" / "synthetic"
FONT_SIZE = 12
LEFT = 72
LINE_HEIGHT = 24


@dataclasses.dataclass(frozen=True)
class SyntheticPage:
    """One page to lay out.

    Attributes:
        lines: Text lines, written top to bottom.
        names: Names whose every occurrence is recorded as ground truth.
        rotation: Page ``/Rotate`` value; text is placed upright on the
            displayed page.
    """

    lines: tuple[str, ...]
    names: tuple[str, ...]
    rotation: int = 0


CASES: dict[str, tuple[SyntheticPage, ...]] = {
    "accents": (
        SyntheticPage(
            lines=(
                "Dr. María González chaired the review.",
                "José Núñez presented the budget.",
                "The minutes were taken by François Lefèvre.",
                "Jürgen Müller and María González agreed.",
            ),
            names=(
                "María González",
                "José Núñez",
                "François Lefèvre",
                "Jürgen Müller",
            ),
        ),
    ),
    "two_per_line": (
        SyntheticPage(
            lines=(
                "Anna Berg and Lucas Moreau reviewed the draft.",
                "Approved by Peter Novak, Ines Vidal.",
            ),
            names=("Anna Berg", "Lucas Moreau", "Peter Novak", "Ines Vidal"),
        ),
    ),
    "rotated": (
        SyntheticPage(
            lines=("Report prepared by Helen Carter.",),
            names=("Helen Carter",),
        ),
        SyntheticPage(
            lines=(
                "Landscape appendix signed by Omar Haddad.",
                "Reviewed by Prof. Helen Carter.",
            ),
            names=("Omar Haddad", "Helen Carter"),
            rotation=90,
        ),
    ),
}


def lay_out(document: pymupdf.Document, spec: SyntheticPage) -> pymupdf.Page:
    """Adds an A4 page with ``spec`` written upright on the displayed page.

    Args:
        document: The document to extend.
        spec: The page content.

    Returns:
        The new page.
    """
    page = document.new_page(width=595, height=842)
    page.set_rotation(spec.rotation)
    for index, line in enumerate(spec.lines):
        origin = pymupdf.Point(LEFT, LEFT + index * LINE_HEIGHT)
        page.insert_text(
            origin * page.derotation_matrix,
            line,
            fontname="helv",
            fontsize=FONT_SIZE,
            rotate=spec.rotation,
        )
    return page


def name_boxes(page: pymupdf.Page, name: str) -> list[dict[str, float]]:
    """Returns the displayed-page box of every occurrence of ``name``.

    Args:
        page: A laid-out page.
        name: The exact name as written.

    Returns:
        One box per occurrence, as ``x``, ``y``, ``width``, ``height``.
    """
    boxes = []
    for hit in page.search_for(name):
        rect = hit * page.rotation_matrix
        boxes.append(
            {
                "x": round(rect.x0, 2),
                "y": round(rect.y0, 2),
                "width": round(rect.width, 2),
                "height": round(rect.height, 2),
            }
        )
    return boxes


def build(
    case: str, pages: tuple[SyntheticPage, ...], out_dir: pathlib.Path
) -> None:
    """Writes ``<case>.pdf`` and its ground truth ``<case>.json``.

    Args:
        case: Case name, used as the file stem.
        pages: Page specifications in order.
        out_dir: Output directory.
    """
    entries = []
    with pymupdf.open() as document:
        for spec in pages:
            page = lay_out(document, spec)
            for name in spec.names:
                for box in name_boxes(page, name):
                    entries.append(
                        {"name": name, "page_number": page.number, **box}
                    )
        document.save(out_dir / f"{case}.pdf", garbage=4, deflate=True)
    truth = {
        "document": f"{case}.pdf",
        "page_count": len(pages),
        "names": entries,
    }
    (out_dir / f"{case}.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False) + "\n"
    )


def build_all(out_dir: pathlib.Path) -> None:
    """Writes every synthetic case into ``out_dir``.

    Args:
        out_dir: Existing output directory.
    """
    # Box height equals the font size, close to the tight boxes OCR returns.
    pymupdf.TOOLS.set_small_glyph_heights(True)
    try:
        for case, pages in CASES.items():
            build(case, pages, out_dir)
    finally:
        pymupdf.TOOLS.set_small_glyph_heights(False)


def main() -> None:
    """Writes every synthetic case."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=pathlib.Path, default=OUT_DIR)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    build_all(args.out_dir)


if __name__ == "__main__":
    main()
