"""Acceptance: the real pipeline finds every verified name box, nothing else.

Runs PyMuPDF, Tesseract and the configured spaCy model on the provided
sample PDFs, checked against the human-verified ground truth, and on
synthetic PDFs whose boxes come from their layout.
"""

import functools
import json
from pathlib import Path
from typing import Any

import pytest

from app.adapters.cpu_runner.thread_runner import ThreadCpuRunner
from app.adapters.pymupdf.page_renderer import PyMuPdfRenderer
from app.adapters.spacy_ner.ner import SpacyNer
from app.adapters.tesseract.ocr import TesseractOcr
from app.config import Settings
from app.domain.extraction import Box
from app.domain.extraction import NameOccurrence
from app.domain.normalize import normalize_name
from app.service_layer.extract import ExtractNames
from scripts.make_synthetic_pdfs import CASES
from scripts.make_synthetic_pdfs import build_all
from tests.fakes.name_matcher import ScriptedNameMatcher

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xfail(
        strict=True, raises=NotImplementedError, reason="adapters not built"
    ),
]

REPO = Path(__file__).parents[2]
GROUND_TRUTH = REPO / "tests" / "data" / "ground_truth"
SAMPLES = REPO / "sample_pdfs"
MIN_IOU = 0.5


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generates the synthetic PDFs and their ground truth once per session.

    Args:
        tmp_path_factory: Pytest's session temp directory factory.

    Returns:
        The directory holding ``<case>.pdf`` and ``<case>.json``.
    """
    out_dir = tmp_path_factory.mktemp("synthetic")
    build_all(out_dir)
    return out_dir


@functools.cache
def extract_names() -> ExtractNames:
    """Builds the use case from the real adapters and default settings.

    Returns:
        The use case, built once per test session.
    """
    settings = Settings(_env_file=None)
    return ExtractNames(
        renderer=PyMuPdfRenderer(dpi=settings.render.dpi),
        ocr=TesseractOcr(settings.ocr.languages, settings.ocr.timeout_s),
        ner=SpacyNer.load(settings.ner.model),
        matcher=ScriptedNameMatcher({}),
        cpu=ThreadCpuRunner(settings.cpu.max_concurrency),
        threshold=settings.matcher.threshold,
    )


def iou(box: Box, truth: dict[str, Any]) -> float:
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
    found: tuple[NameOccurrence, ...], truth: list[dict[str, Any]]
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
                and normalize_name(occurrence.name)
                == normalize_name(entry["name"])
                and iou(occurrence.box, entry) >= MIN_IOU
            ),
            None,
        )
        if pair is None:
            missed.append(f"p{entry['page_number']} {entry['name']}")
        else:
            extra.remove(pair)
    return missed, [f"p{o.page_number} {o.name}" for o in extra]


@pytest.mark.parametrize(
    "case",
    ["sample/company_memo", "sample/meeting_minutes", "sample/research_report"]
    + [f"synthetic/{name}" for name in CASES],
)
async def test_every_verified_name_box_is_found_and_nothing_else(
    case: str, synthetic_dir: Path
) -> None:
    kind, stem = case.split("/")
    truth_dir, pdf_dir = (
        (GROUND_TRUTH, SAMPLES) if kind == "sample" else (synthetic_dir,) * 2
    )
    truth = json.loads((truth_dir / f"{stem}.json").read_text())

    pdf = (pdf_dir / truth["document"]).read_bytes()

    result = await extract_names()(pdf, [])

    assert unmatched(result.occurrences, truth["names"]) == ([], [])
