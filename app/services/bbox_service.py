"""
Module: app.services.bbox_service
Path: app/services/bbox_service.py
Description: Service responsible for mapping NER entities to OCR words.
"""

from app.models.ner import NEREntity
from app.models.ocr import OCRPage, OCRWord


class BoundingBoxService:
    """Map detected entities to their corresponding OCR words."""

    def find_matching_words(
        self,
        page: OCRPage,
        entity: NEREntity,
    ) -> list[OCRWord]:
        """Return OCR words whose text spans overlap the entity span."""

        matching_words: list[OCRWord] = []
        cursor = 0

        for word in page.words:
            word_start = cursor
            word_end = word_start + len(word.text)

            if word_start < entity.end and word_end > entity.start:
                matching_words.append(word)

            cursor = word_end + 1

        return matching_words

    def create_bounding_box(
        self,
        words: list[OCRWord],
    ) -> tuple[float, float, float, float] | None:
        """Create a PDF-space bounding box from OCR words."""

        relevant_words = [
            word
            for word in words
            if any(character.isalnum() for character in word.text)
        ]

        if not relevant_words:
            return None

        left = min(word.x for word in relevant_words)
        top = min(word.y for word in relevant_words)
        right = max(word.x + word.width for word in relevant_words)
        bottom = max(word.y + word.height for word in relevant_words)

        return (
            left,
            top,
            right - left,
            bottom - top,
        )
