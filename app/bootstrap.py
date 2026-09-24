"""Composition root: builds adapters and use cases from Settings."""

import dataclasses

from app import config
from app.adapters.cpu_runner import thread_runner
from app.adapters.fuzzy import name_matcher
from app.adapters.pymupdf import page_renderer
from app.adapters.spacy_ner import ner
from app.adapters.tesseract import ocr
from app.service_layer import extract


@dataclasses.dataclass(frozen=True, slots=True)
class Container:
    """The use cases the API and the worker call.

    Attributes:
        extract_names: Finds and matches person names in a PDF.
    """

    extract_names: extract.ExtractNames


def build_container(settings: config.Settings) -> Container:
    """Loads every model and client once and wires the use cases.

    Args:
        settings: The service configuration.

    Returns:
        The wired use cases.
    """
    return Container(
        extract_names=extract.ExtractNames(
            renderer=page_renderer.PyMuPdfRenderer(settings.render.dpi),
            ocr=ocr.TesseractOcr(
                settings.ocr.languages, settings.ocr.timeout_s
            ),
            ner=ner.SpacyNer.load(settings.ner.model),
            matcher=name_matcher.RapidFuzzNameMatcher(),
            cpu=thread_runner.ThreadCpuRunner(settings.cpu.max_concurrency),
            threshold=settings.matcher.threshold,
        )
    )
