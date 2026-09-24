"""Use case: find every person name in a PDF and match it to queried names."""

import asyncio
from collections.abc import Sequence

from app.domain.extraction import EntitySpan
from app.domain.extraction import ExtractionResult
from app.domain.extraction import NameMatch
from app.domain.extraction import NameOccurrence
from app.domain.extraction import PageImage
from app.domain.extraction import PageText
from app.domain.extraction import QueryName
from app.domain.page_text import build_page_text
from app.domain.propagation import propagate
from app.domain.span_boxes import locate_span
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

    async def __call__(
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
        pages = await self._cpu.run(self._renderer.render, pdf)
        tagged = await asyncio.gather(*(self._tag(page) for page in pages))
        accepted = {
            occurrence.name
            for text, spans in tagged
            for span in spans
            for occurrence in locate_span(text, span)
        }
        occurrences: list[NameOccurrence] = []
        for text, spans in tagged:
            found = [*spans, *propagate(text, accepted, spans)]
            for span in sorted(found, key=lambda span: span.start):
                occurrences.extend(locate_span(text, span))
        return ExtractionResult(
            occurrences=tuple(occurrences),
            matches=tuple(self._match(occurrences, queries)),
        )

    async def _tag(self, page: PageImage) -> tuple[PageText, list[EntitySpan]]:
        """Reads one page and finds its PERSON spans.

        Args:
            page: The rendered page.

        Returns:
            The page text and the spans NER tagged in it.
        """
        words = await self._cpu.run(self._ocr.read, page)
        text = build_page_text(words)
        spans = await self._cpu.run(self._ner.find_persons, text.text)
        return text, spans

    def _match(
        self,
        occurrences: Sequence[NameOccurrence],
        queries: Sequence[QueryName],
    ) -> list[NameMatch]:
        """Scores each distinct extracted name against every queried name.

        Args:
            occurrences: The occurrences, in document order.
            queries: The queried names, in request order.

        Returns:
            The pairs scoring at least the threshold.
        """
        names = dict.fromkeys(occurrence.name for occurrence in occurrences)
        matches = []
        for name in names:
            for query in queries:
                score = self._matcher.similarity(name, query.full_name)
                if score >= self._threshold:
                    matches.append(NameMatch(name, query.full_name, score))
        return matches
