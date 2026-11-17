"""Recover repeated names from existing page-local OCR words, without rerunning NER."""

from bisect import bisect_left
from dataclasses import dataclass
from heapq import merge

from thefuzz import fuzz

from app.models.extraction import PersonSpan
from app.models.schemas import ExtractedName
from app.services.bbox_service import PageLocator
from app.services.fuzzy_service import normalize_name


# Counted across all pages and enabled passes. They bound actual work, not only
# the number of successful results. Exceeding any limit rejects the extraction.
MAX_RECOVERY_WINDOWS = 100_000
MAX_RECOVERY_COMPARISONS = 100_000
MAX_RECOVERY_WORK_UNITS = 100_000_000
MAX_SEED_WORDS = 8
MAX_RECOVERY_NAME_CHARS = 512
MIN_COMPACT_CHARS = 8
COMPONENT_FUZZY_THRESHOLD = 80  # Independent of the query-name fuzzy threshold.
MAX_CHANGED_COMPONENTS = 2
_AMBIGUOUS = object()


class NameRecoveryLimitError(ValueError):
    """Recovery exceeded a bounded resource or would exceed the result limit."""


@dataclass(frozen=True)
class LocatedOccurrence:
    span: PersonSpan
    location: ExtractedName
    stage: int = 0


@dataclass(frozen=True)
class RecoveryPage:
    locator: PageLocator
    ner_occurrences: tuple[LocatedOccurrence, ...]


@dataclass(frozen=True)
class RecoveryResult:
    occurrences: tuple[LocatedOccurrence, ...]
    ambiguous_groups: int


class _Budget:
    def __init__(self):
        self.windows = 0
        self.comparisons = 0
        self.work = 0

    def window(self):
        self.windows += 1
        if self.windows > MAX_RECOVERY_WINDOWS:
            raise NameRecoveryLimitError("Name recovery window limit exceeded")

    def compare(self, left: str, right: str):
        self.comparisons += 1
        self.work += len(left) * len(right)
        if self.comparisons > MAX_RECOVERY_COMPARISONS or self.work > MAX_RECOVERY_WORK_UNITS:
            raise NameRecoveryLimitError("Name recovery comparison limit exceeded")

    def normalize(self, text: str) -> str:
        self.work += len(text)
        if self.work > MAX_RECOVERY_WORK_UNITS:
            raise NameRecoveryLimitError("Name recovery normalization limit exceeded")
        return normalize_name(text)


class _Intervals:
    """Sorted, merged half-open ranges used to protect existing OCR positions."""

    def __init__(self, spans=()):
        self.starts = []
        self.ends = []
        self.extend(sorted(spans))

    def overlaps(self, start: int, end: int) -> bool:
        index = bisect_left(self.starts, end) - 1
        return index >= 0 and self.ends[index] > start

    def extend(self, spans) -> None:
        """Merge a sorted batch in linear time, avoiding quadratic insertion."""
        starts, ends = [], []
        for start, end in merge(zip(self.starts, self.ends), spans):
            if starts and ends[-1] >= start:
                ends[-1] = max(ends[-1], end)
            else:
                starts.append(start)
                ends.append(end)
        self.starts, self.ends = starts, ends


def _at_most_one_edit(left: str, right: str) -> bool:
    """Levenshtein distance at most one, with bounded linear work."""
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    while index < len(shorter) and shorter[index] == longer[index]:
        index += 1
    return shorter[index:] == longer[index + 1:]


def _fuzzy_match(candidate: str, seed: str) -> bool:
    candidate_words, seed_words = candidate.split(), seed.split()
    if len(candidate_words) != len(seed_words):
        return False
    changes = 0
    for left, right in zip(candidate_words, seed_words, strict=True):
        if left == right:
            continue
        if (min(len(left), len(right)) <= 3 or not _at_most_one_edit(left, right)
                or fuzz.ratio(left, right) < COMPONENT_FUZZY_THRESHOLD):
            return False
        changes += 1
        if changes > MAX_CHANGED_COMPONENTS:
            return False
    return changes > 0


def recover_names(pages: list[RecoveryPage], *, passes: int, max_name_chars: int, max_new: int) -> RecoveryResult:
    """Search only validated NER references and existing OCR words.

    Existing/ambiguous positions are protected across passes. Candidates with
    overlapping alternatives are refused rather than resolved by iteration order.
    The caller maps NameRecoveryLimitError to its HTTP complexity error.
    """
    if type(passes) is not int or not 0 <= passes <= 3 or max_name_chars <= 0 or max_new < 0:
        raise ValueError("Invalid name recovery configuration")
    if passes == 0:
        return RecoveryResult((), 0)

    budget = _Budget()
    max_chars = min(max_name_chars, MAX_RECOVERY_NAME_CHARS)
    seeds = sorted({
        normalized for page in pages for occurrence in page.ner_occurrences
        if len(occurrence.span.text) <= max_chars
        and 2 <= len((normalized := budget.normalize(occurrence.span.text)).split()) <= MAX_SEED_WORDS
    })
    if not seeds:
        return RecoveryResult((), 0)
    seed_set = set(seeds)
    by_word_count = {}
    compact = {}
    for seed in seeds:
        by_word_count.setdefault(len(seed.split()), []).append(seed)
        key = seed.replace(" ", "")
        if len(key) >= MIN_COMPACT_CHARS:
            compact.setdefault(key, []).append(seed)

    occupied = [
        _Intervals((item.span.char_start, item.span.char_end) for item in page.ner_occurrences)
        for page in pages
    ]
    recovered = []
    ambiguous_groups = 0

    for stage in range(1, passes + 1):
        for page_index, page_data in enumerate(pages):
            locator = page_data.locator
            page = locator.page
            if not locator.valid:
                continue
            protected = occupied[page_index]
            cluster_start = cluster_end = None
            cluster_item = None
            cluster_ambiguous = False
            stage_covered = []
            content_words = {}

            def has_content(index):
                if index not in content_words:
                    text = page.words[index].text
                    content_words[index] = len(text) <= max_chars and bool(budget.normalize(text))
                return content_words[index]

            def flush_cluster():
                nonlocal cluster_start, cluster_end, cluster_item, cluster_ambiguous, ambiguous_groups
                if cluster_start is None:
                    return
                # A rejected ambiguity also remains blocked in later passes.
                stage_covered.append((cluster_start, cluster_end))
                if cluster_ambiguous:
                    ambiguous_groups += 1
                else:
                    if len(recovered) >= max_new:
                        raise NameRecoveryLimitError("Name recovery result limit exceeded")
                    recovered.append(cluster_item)
                cluster_start = cluster_end = None
                cluster_item = None
                cluster_ambiguous = False

            for start_index, first in enumerate(page.words):
                for end_index in range(start_index, min(start_index + MAX_SEED_WORDS, len(page.words))):
                    budget.window()
                    last = page.words[end_index]
                    start, end = first.char_start, last.char_end
                    if end - start > max_chars:
                        break
                    if protected.overlaps(start, end):
                        continue
                    # Bullets or standalone punctuation must not produce two
                    # overlapping copies of the same normalized name.
                    if not has_content(start_index) or not has_content(end_index):
                        continue
                    candidate = budget.normalize(page.text[start:end])
                    if not candidate:
                        continue

                    match = None
                    if stage == 1:
                        budget.compare(candidate, candidate)
                        if candidate in seed_set:
                            match = True
                    elif stage == 2:
                        # Exact matches belong only to the earlier pass.
                        if candidate in seed_set:
                            continue
                        for seed in by_word_count.get(len(candidate.split()), ()):
                            budget.compare(candidate, seed)
                            if _fuzzy_match(candidate, seed):
                                if match is not None:
                                    match = _AMBIGUOUS
                                    break
                                match = True
                    else:
                        if candidate in seed_set:
                            continue
                        key = candidate.replace(" ", "")
                        if len(key) < MIN_COMPACT_CHARS:
                            continue
                        budget.compare(candidate, candidate)
                        matches = compact.get(key, ())
                        if len(matches) == 1:
                            match = True
                        elif len(matches) > 1:
                            match = _AMBIGUOUS
                    if match is None:
                        continue
                    span = PersonSpan(page.text[start:end], start, end)
                    location = locator.locate(span)
                    if location is None:
                        continue
                    item = LocatedOccurrence(span, location, stage)
                    if cluster_start is not None and start >= cluster_end:
                        flush_cluster()
                    if cluster_start is None:
                        cluster_start, cluster_end = start, end
                        cluster_item = item
                        cluster_ambiguous = match is _AMBIGUOUS
                    else:
                        cluster_end = max(cluster_end, end)
                        cluster_ambiguous = True
            flush_cluster()
            # Current-stage clusters are visited in OCR order; later passes
            # see both accepted and ambiguous intervals as protected.
            protected.extend(stage_covered)

    return RecoveryResult(tuple(recovered), ambiguous_groups)
