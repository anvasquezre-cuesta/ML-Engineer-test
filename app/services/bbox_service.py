"""Map detected person mentions to OCR word bounding boxes."""

import logging
from collections import defaultdict
from collections.abc import Sequence
from time import perf_counter

from thefuzz import fuzz

from app.config import Settings
from app.models.domain import OCRDocument, OCRPage, OCRWord, PersonMention
from app.models.schemas import BoundingBox, ExtractedName
from app.services.text_normalization import normalize_name

logger = logging.getLogger(__name__)


class BoundingBoxMappingError(RuntimeError):
    """Raised when OCR and NER page metadata is inconsistent."""


class OCRBoundingBoxService:
    """Locate person mentions using offsets with a constrained fuzzy fallback."""

    def __init__(self, settings: Settings) -> None:
        self._match_threshold = settings.bbox_match_threshold
        self._max_gap_factor = settings.bbox_max_horizontal_gap_factor

    def locate(
        self,
        document: OCRDocument,
        mentions: Sequence[PersonMention],
    ) -> tuple[ExtractedName, ...]:
        """Return one merged PDF-space box for each located mention occurrence."""

        started_at = perf_counter()
        located_names: list[ExtractedName] = []

        for mention in sorted(
            mentions,
            key=lambda item: (item.page_number, item.start, item.end),
        ):
            page = self._get_page(document, mention)
            words = self._words_for_span(page, mention)

            if not self._matches_name(mention.name, words):
                words = self._find_fuzzy_words(page, mention)

            if not words:
                logger.warning(
                    "Bounding box not found: page=%s, start=%s, end=%s",
                    mention.page_number,
                    mention.start,
                    mention.end,
                )
                continue

            located_names.append(
                ExtractedName(
                    name=mention.name,
                    bounding_box=self._merge_boxes(words, mention.page_number),
                )
            )

        duration_ms = (perf_counter() - started_at) * 1000
        logger.info(
            "Bounding-box mapping completed: mentions=%s, located=%s, "
            "duration_ms=%.2f",
            len(mentions),
            len(located_names),
            duration_ms,
        )
        return tuple(located_names)

    @staticmethod
    def _get_page(document: OCRDocument, mention: PersonMention) -> OCRPage:
        if mention.page_number >= len(document.pages):
            logger.error(
                "NER mention references missing OCR page: page=%s",
                mention.page_number,
            )
            raise BoundingBoxMappingError(
                f"NER mention references missing page {mention.page_number}"
            )

        page = document.pages[mention.page_number]
        if mention.end > len(page.text):
            logger.error(
                "NER mention offsets exceed OCR text: page=%s, end=%s, text_length=%s",
                mention.page_number,
                mention.end,
                len(page.text),
            )
            raise BoundingBoxMappingError(
                f"NER mention offsets exceed page {mention.page_number} text"
            )
        return page

    @staticmethod
    def _words_for_span(
        page: OCRPage,
        mention: PersonMention,
    ) -> tuple[OCRWord, ...]:
        return tuple(
            word
            for word in page.words
            if word.start < mention.end and word.end > mention.start
        )

    def _matches_name(self, name: str, words: Sequence[OCRWord]) -> bool:
        if not words:
            return False
        candidate = " ".join(word.text for word in words)
        return self._similarity(name, candidate) >= self._match_threshold

    def _find_fuzzy_words(
        self,
        page: OCRPage,
        mention: PersonMention,
    ) -> tuple[OCRWord, ...]:
        target_word_count = max(1, len(normalize_name(mention.name).split()))
        window_sizes = range(max(1, target_word_count - 1), target_word_count + 2)
        lines: dict[tuple[int, int, int], list[OCRWord]] = defaultdict(list)

        for word in page.words:
            line_key = (
                word.block_number,
                word.paragraph_number,
                word.line_number,
            )
            lines[line_key].append(word)

        best_words: tuple[OCRWord, ...] = ()
        best_score = 0.0
        best_distance = float("inf")

        for line_words in lines.values():
            for window_size in window_sizes:
                for start_index in range(len(line_words) - window_size + 1):
                    candidate = tuple(
                        line_words[start_index : start_index + window_size]
                    )
                    if not self._has_reasonable_gaps(candidate):
                        continue

                    candidate_text = " ".join(word.text for word in candidate)
                    score = self._similarity(mention.name, candidate_text)
                    distance = abs(candidate[0].start - mention.start)
                    if score < self._match_threshold:
                        continue
                    if score > best_score or (
                        score == best_score and distance < best_distance
                    ):
                        best_words = candidate
                        best_score = score
                        best_distance = distance

        return best_words

    def _has_reasonable_gaps(self, words: Sequence[OCRWord]) -> bool:
        for current, following in zip(words, words[1:], strict=False):
            current_box = current.bounding_box
            following_box = following.bounding_box
            horizontal_gap = following_box.x - (
                current_box.x + current_box.width
            )
            allowed_gap = (
                max(current_box.height, following_box.height) * self._max_gap_factor
            )
            if horizontal_gap > allowed_gap:
                return False
        return True

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        normalized_left = normalize_name(left)
        normalized_right = normalize_name(right)
        if not normalized_left or not normalized_right:
            return 0.0
        return fuzz.ratio(normalized_left, normalized_right) / 100

    @staticmethod
    def _merge_boxes(
        words: Sequence[OCRWord],
        page_number: int,
    ) -> BoundingBox:
        x1 = min(word.bounding_box.x for word in words)
        y1 = min(word.bounding_box.y for word in words)
        x2 = max(
            word.bounding_box.x + word.bounding_box.width for word in words
        )
        y2 = max(
            word.bounding_box.y + word.bounding_box.height for word in words
        )
        return BoundingBox(
            page_number=page_number,
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
        )
