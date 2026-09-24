"""Extraction use case: page coverage, document-wide recovery, matching."""

from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import Sequence

from app.domain.extraction import ExtractionResult
from app.domain.extraction import NameMatch
from app.domain.extraction import NameOccurrence
from app.domain.extraction import PageWords
from app.domain.extraction import QueryName
from app.service_layer.extract import ExtractNames
from tests.builders import box_of
from tests.builders import page_words
from tests.builders import union
from tests.fakes.cpu_runner import InlineCpuRunner
from tests.fakes.name_matcher import ScriptedNameMatcher
from tests.fakes.ner import ExactNer
from tests.fakes.ocr import ScriptedOcr
from tests.fakes.page_renderer import BlankPageRenderer


async def extract(
    pages: Sequence[PageWords],
    persons: Collection[str],
    queries: Sequence[QueryName] = (),
    scores: Mapping[tuple[str, str], float] | None = None,
    threshold: float = 0.9,
) -> ExtractionResult:
    """Runs the use case over scripted pages.

    Args:
        pages: OCR words of each page.
        persons: Strings the fake NER tags.
        queries: Names to match against.
        scores: Matcher score per ``(extracted, queried)`` pair.
        threshold: Minimum score to report a match.

    Returns:
        The extraction result.
    """
    use_case = ExtractNames(
        renderer=BlankPageRenderer(len(pages)),
        ocr=ScriptedOcr(pages),
        ner=ExactNer(persons),
        matcher=ScriptedNameMatcher(scores or {}),
        cpu=InlineCpuRunner(),
        threshold=threshold,
    )
    return await use_case(b"%PDF-1.7", queries)


async def test_every_page_is_read_and_keeps_its_page_number() -> None:
    pages = [
        page_words([["Anna Berg signed"]], page_number=0),
        page_words([["nothing to see"]], page_number=1),
        page_words([["approved by Lucas Moreau"]], page_number=2),
    ]

    result = await extract(pages, persons={"Anna Berg", "Lucas Moreau"})

    assert result.occurrences == (
        NameOccurrence(
            name="Anna Berg",
            page_number=0,
            box=union(box_of(pages[0], "Anna"), box_of(pages[0], "Berg")),
        ),
        NameOccurrence(
            name="Lucas Moreau",
            page_number=2,
            box=union(box_of(pages[2], "Lucas"), box_of(pages[2], "Moreau")),
        ),
    )


async def test_name_tagged_with_a_title_is_recovered_on_other_pages() -> None:
    pages = [
        page_words([["Dr. Elizabeth Park opened"]], page_number=0),
        page_words([["Elizabeth Park closed"]], page_number=1),
    ]

    result = await extract(pages, persons={"Dr. Elizabeth Park"})

    assert [(o.name, o.page_number) for o in result.occurrences] == [
        ("Elizabeth Park", 0),
        ("Elizabeth Park", 1),
    ]
    assert result.occurrences[1].box == union(
        box_of(pages[1], "Elizabeth"), box_of(pages[1], "Park")
    )


async def test_matches_each_name_once_per_query_at_or_above_threshold() -> None:
    pages = [
        page_words([["Anna Berg and Lukas Moreau met"]], page_number=0),
        page_words([["Anna Berg left"]], page_number=1),
    ]

    result = await extract(
        pages,
        persons={"Anna Berg", "Lukas Moreau"},
        queries=[QueryName("Lucas", "Moreau"), QueryName("Anna", "Berg")],
        scores={
            ("Anna Berg", "Anna Berg"): 1.0,
            ("Anna Berg", "Lucas Moreau"): 0.89,
            ("Lukas Moreau", "Lucas Moreau"): 0.9,
        },
        threshold=0.9,
    )

    assert result.matches == (
        NameMatch("Anna Berg", "Anna Berg", 1.0),
        NameMatch("Lukas Moreau", "Lucas Moreau", 0.9),
    )
