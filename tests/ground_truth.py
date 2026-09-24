"""Comparison of pipeline output with the verified name-box ground truth."""

import pathlib
from typing import Any

from app.domain import extraction
from app.domain import normalize

REPO = pathlib.Path(__file__).parents[1]
GROUND_TRUTH = REPO / "tests" / "data" / "ground_truth"
SAMPLES = REPO / "sample_pdfs"
MIN_IOU = 0.5


def iou(box: extraction.Box, truth: dict[str, Any]) -> float:
    """Returns the intersection over union of a box and a truth entry.

    Args:
        box: A predicted box.
        truth: A ground-truth entry with ``x``, ``y``, ``width``, ``height``.

    Returns:
        The IoU in 0..1.
    """
    x0, y0 = max(box.x, truth["x"]), max(box.y, truth["y"])
    x1 = min(box.x + box.width, truth["x"] + truth["width"])
    y1 = min(box.y + box.height, truth["y"] + truth["height"])
    overlap = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = box.width * box.height + truth["width"] * truth["height"] - overlap
    return float(overlap / union)


def unmatched(
    found: tuple[extraction.NameOccurrence, ...], truth: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Pairs occurrences with truth entries one to one.

    A pair needs the same normalized name, the same page and ``MIN_IOU``.

    Args:
        found: The occurrences the pipeline returned.
        truth: The expected entries.

    Returns:
        The truth entries left unmatched and the extra occurrences.
    """
    extra = list(found)
    missed = []
    for entry in truth:
        pair = next(
            (
                occurrence
                for occurrence in extra
                if occurrence.page_number == entry["page_number"]
                and normalize.normalize_name(occurrence.name)
                == normalize.normalize_name(entry["name"])
                and iou(occurrence.box, entry) >= MIN_IOU
            ),
            None,
        )
        if pair is None:
            missed.append(f"p{entry['page_number']} {entry['name']}")
        else:
            extra.remove(pair)
    return missed, [f"p{o.page_number} {o.name}" for o in extra]
