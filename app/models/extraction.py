"""
Module: app.models.extraction
Path: app/models/extraction.py
Description: Internal data models used by the extraction workflow.
"""


class ExtractedNameResult:
    """Represent an extracted person name and its PDF-space location."""

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
