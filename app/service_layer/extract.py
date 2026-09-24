"""Use case: find every person name in a PDF and match it to queried names."""

from collections.abc import Sequence

from app.domain.extraction import ExtractionResult
from app.domain.extraction import QueryName
from app.ports.cpu_runner import CpuRunner
from app.ports.name_matcher import NameMatcher
from app.ports.ner import Ner
from app.ports.ocr import Ocr
from app.ports.page_renderer import PageRenderer


class ExtractNames:
    """Locates person names on every page and fuzzy-matches them."""

    def __init__(
        self,
        renderer: PageRenderer,
        ocr: Ocr,
        ner: Ner,
        matcher: NameMatcher,
        cpu: CpuRunner,
        threshold: float,
    ) -> None:
        """Initializes the use case.

        Args:
            renderer: Turns the PDF into page images.
            ocr: Reads the words on each page.
            ner: Finds PERSON spans in page text.
            matcher: Scores extracted names against queried names.
            cpu: Runs the blocking rendering, OCR and NER calls.
            threshold: Minimum similarity, in 0..1, to report a match.
        """
        self._renderer = renderer
        self._ocr = ocr
        self._ner = ner
        self._matcher = matcher
        self._cpu = cpu
        self._threshold = threshold

    async def __call__(  # noqa: DOC501, DOC503
        self, pdf: bytes, queries: Sequence[QueryName]
    ) -> ExtractionResult:
        """Extracts the names in ``pdf`` and matches them to ``queries``.

        Names tagged anywhere in the document, without titles, are also
        searched on every page to recover repeats NER missed. Each distinct
        extracted name is reported once per queried name it matches with a
        similarity of at least the threshold.

        Args:
            pdf: The validated PDF content.
            queries: Names to match against.

        Returns:
            The name occurrences with their boxes, and the matches.
        """
        raise NotImplementedError
