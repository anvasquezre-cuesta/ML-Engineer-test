"""Acceptance: the real pipeline finds every verified name box, nothing else.

Runs PyMuPDF, Tesseract and the configured spaCy model on the provided
sample PDFs, checked against the human-verified ground truth, and on
synthetic PDFs whose boxes come from their layout.
"""

import functools
import json
import pathlib

import pytest

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.pymupdf import page_renderer
from app.adapters.spacy_ner import ner as spacy_ner
from app.adapters.tesseract import ocr as tesseract_ocr
from app.service_layer import extract
from scripts import make_synthetic_pdfs
from tests import ground_truth
from tests.fakes import name_matcher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def synthetic_dir(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Generates the synthetic PDFs and their ground truth once per session.

    Args:
        tmp_path_factory: Pytest's session temp directory factory.

    Returns:
        The directory holding ``<case>.pdf`` and ``<case>.json``.
    """
    out_dir = tmp_path_factory.mktemp("synthetic")
    make_synthetic_pdfs.build_all(out_dir)
    return out_dir


@functools.cache
def extract_names() -> extract.ExtractNames:
    """Builds the use case from the real adapters and default settings.

    Returns:
        The use case, built once per test session.
    """
    settings = config.Settings(_env_file=None)
    return extract.ExtractNames(
        renderer=page_renderer.PyMuPdfRenderer(dpi=settings.render.dpi),
        ocr=tesseract_ocr.TesseractOcr(
            settings.ocr.languages, settings.ocr.timeout_s
        ),
        ner=spacy_ner.SpacyNer.load(settings.ner.model),
        matcher=name_matcher.ScriptedNameMatcher({}),
        cpu=thread_runner.ThreadCpuRunner(settings.cpu.max_concurrency),
        threshold=settings.matcher.threshold,
    )


@pytest.mark.parametrize(
    "case",
    ["sample/company_memo", "sample/meeting_minutes", "sample/research_report"]
    + [f"synthetic/{name}" for name in make_synthetic_pdfs.CASES],
)
async def test_every_verified_name_box_is_found_and_nothing_else(
    case: str, synthetic_dir: pathlib.Path
) -> None:
    kind, stem = case.split("/")
    truth_dir, pdf_dir = (
        (ground_truth.GROUND_TRUTH, ground_truth.SAMPLES)
        if kind == "sample"
        else (synthetic_dir,) * 2
    )
    truth = json.loads((truth_dir / f"{stem}.json").read_text())

    pdf = (pdf_dir / truth["document"]).read_bytes()

    result = await extract_names()(pdf, [])

    assert ground_truth.unmatched(result.occurrences, truth["names"]) == (
        [],
        [],
    )
