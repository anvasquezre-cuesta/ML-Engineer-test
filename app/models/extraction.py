"""
Module: app.models.extraction
Path: app/models/extraction.py
Description: Internal data models used by document extraction.
"""

from app.models.fuzzy import FuzzyMatchResult


class ExtractedNameResult:
    """Represent an extracted person name and its bounding box."""

    def __init__(
        self,
        name: str,
        page_number: int,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        self.name = name
        self.page_number = page_number
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class ExtractionResult:
    """Represent the complete document extraction result."""

    def __init__(
        self,
        extracted_names: list[ExtractedNameResult],
        fuzzy_matches: list[FuzzyMatchResult],
    ) -> None:
        self.extracted_names = extracted_names
        self.fuzzy_matches = fuzzy_matches
