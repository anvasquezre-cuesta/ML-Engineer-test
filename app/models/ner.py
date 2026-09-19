"""
Module: app.models.ner
Path: app/models/ner.py
Description: Internal data models used to represent NER results.
"""


class NEREntity:
    """Represent one entity detected by named entity recognition."""

    def __init__(
        self,
        text: str,
        label: str,
        page_number: int,
    ) -> None:
        self.text = text
        self.label = label
        self.page_number = page_number
