"""Use case: find every person name in a PDF and match it to queried names."""

import asyncio
from collections.abc import Sequence

from app.domain import extraction
from app.domain import page_text
from app.domain import propagation
from app.domain import span_boxes
from app.ports import cpu_runner
from app.ports import name_matcher
from app.ports import ner as ner_port
from app.ports import ocr as ocr_port
from app.ports import page_renderer


class ExtractNames:
    """Locates person names on every page and fuzzy-matches them."""

    def __init__(
        self,
        renderer: page_renderer.PageRenderer,
        ocr: ocr_port.Ocr,
        ner: ner_port.Ner,
        matcher: name_matcher.NameMatcher,
        cpu: cpu_runner.CpuRunner,
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
        self, pdf: bytes, queries: Sequence[extraction.QueryName]
    ) -> extraction.ExtractionResult:
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
            for occurrence in span_boxes.locate_span(text, span)
        }
        occurrences: list[extraction.NameOccurrence] = []
        for text, spans in tagged:
            found = [*spans, *propagation.propagate(text, accepted, spans)]
            for span in sorted(found, key=lambda span: span.start):
                occurrences.extend(span_boxes.locate_span(text, span))
        return extraction.ExtractionResult(
            occurrences=tuple(occurrences),
            matches=tuple(self._match(occurrences, queries)),
        )

    async def _tag(
        self, page: extraction.PageImage
    ) -> tuple[extraction.PageText, list[extraction.EntitySpan]]:
        """Reads one page and finds its PERSON spans.

        Args:
            page: The rendered page.

        Returns:
            The page text and the spans NER tagged in it.
        """
        words = await self._cpu.run(self._ocr.read, page)
        text = page_text.build_page_text(words)
        spans = await self._cpu.run(self._ner.find_persons, text.text)
        return text, spans

    def _match(
        self,
        occurrences: Sequence[extraction.NameOccurrence],
        queries: Sequence[extraction.QueryName],
    ) -> list[extraction.NameMatch]:
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
                    matches.append(
                        extraction.NameMatch(name, query.full_name, score)
                    )
        return matches
