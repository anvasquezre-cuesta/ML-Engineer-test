"""
Module: app.models.fuzzy
Path: app/models/fuzzy.py
Description: Internal data models used by fuzzy name matching.
"""


class FuzzyMatchResult:
    """Represent a fuzzy match between an extracted and supplied name."""

    def __init__(
        self,
        extracted_name: str,
        matched_name: str,
        score: float,
    ) -> None:
        self.extracted_name = extracted_name
        self.matched_name = matched_name
        self.score = score
