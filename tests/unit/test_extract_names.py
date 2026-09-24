"""Extraction use case: page coverage, document-wide recovery, matching."""

from collections.abc import Collection
from collections.abc import Mapping
from collections.abc import Sequence

from app.domain import extraction
from app.service_layer import extract as extract_service
from tests import builders
from tests.fakes import cpu_runner
from tests.fakes import name_matcher
from tests.fakes import ner as ner_fake
from tests.fakes import ocr as ocr_fake
from tests.fakes import page_renderer


async def extract(
    pages: Sequence[extraction.PageWords],
    persons: Collection[str],
    queries: Sequence[extraction.QueryName] = (),
    scores: Mapping[tuple[str, str], float] | None = None,
    threshold: float = 0.9,
) -> extraction.ExtractionResult:
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
    use_case = extract_service.ExtractNames(
        renderer=page_renderer.BlankPageRenderer(len(pages)),
        ocr=ocr_fake.ScriptedOcr(pages),
        ner=ner_fake.ExactNer(persons),
        matcher=name_matcher.ScriptedNameMatcher(scores or {}),
        cpu=cpu_runner.InlineCpuRunner(),
        threshold=threshold,
    )
    return await use_case(b"%PDF-1.7", queries)


async def test_every_page_is_read_and_keeps_its_page_number() -> None:
    pages = [
        builders.page_words([["Anna Berg signed"]], page_number=0),
        builders.page_words([["nothing to see"]], page_number=1),
        builders.page_words([["approved by Lucas Moreau"]], page_number=2),
    ]

    result = await extract(pages, persons={"Anna Berg", "Lucas Moreau"})

    assert result.occurrences == (
        extraction.NameOccurrence(
            name="Anna Berg",
            page_number=0,
            box=builders.union(
                builders.box_of(pages[0], "Anna"),
                builders.box_of(pages[0], "Berg"),
            ),
        ),
        extraction.NameOccurrence(
            name="Lucas Moreau",
            page_number=2,
            box=builders.union(
                builders.box_of(pages[2], "Lucas"),
                builders.box_of(pages[2], "Moreau"),
            ),
        ),
    )


async def test_name_tagged_with_a_title_is_recovered_on_other_pages() -> None:
    pages = [
        builders.page_words([["Dr. Elizabeth Park opened"]], page_number=0),
        builders.page_words([["Elizabeth Park closed"]], page_number=1),
    ]

    result = await extract(pages, persons={"Dr. Elizabeth Park"})

    assert [(o.name, o.page_number) for o in result.occurrences] == [
        ("Elizabeth Park", 0),
        ("Elizabeth Park", 1),
    ]
    assert result.occurrences[1].box == builders.union(
        builders.box_of(pages[1], "Elizabeth"),
        builders.box_of(pages[1], "Park"),
    )


async def test_matches_each_name_once_per_query_at_or_above_threshold() -> None:
    pages = [
        builders.page_words(
            [["Anna Berg and Lukas Moreau met"]], page_number=0
        ),
        builders.page_words([["Anna Berg left"]], page_number=1),
    ]

    result = await extract(
        pages,
        persons={"Anna Berg", "Lukas Moreau"},
        queries=[
            extraction.QueryName("Lucas", "Moreau"),
            extraction.QueryName("Anna", "Berg"),
        ],
        scores={
            ("Anna Berg", "Anna Berg"): 1.0,
            ("Anna Berg", "Lucas Moreau"): 0.89,
            ("Lukas Moreau", "Lucas Moreau"): 0.9,
        },
        threshold=0.9,
    )

    assert result.matches == (
        extraction.NameMatch("Anna Berg", "Anna Berg", 1.0),
        extraction.NameMatch("Lukas Moreau", "Lucas Moreau", 0.9),
    )
