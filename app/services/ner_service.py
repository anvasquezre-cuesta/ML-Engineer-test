"""
Module: app.services.ner_service
Path: app/services/ner_service.py
Description: Service responsible for named entity recognition.
"""

import re

import spacy

from app.models.ner import NEREntity
from app.models.ocr import OCRDocument


class NERService:
    """Identify named entities in OCR text."""

    def __init__(self, nlp: spacy.Language) -> None:
        self.nlp = nlp

    def _normalize_person_name(self, text: str) -> str | None:
        """Normalize and validate a person-name entity."""

        normalized = text.strip(" \t\r\n-–—:;,.")
        tokens = normalized.split()

        if len(tokens) < 2:
            return None

        if not all(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token) for token in tokens):
            return None

        return normalized

    def extract(self, document: OCRDocument) -> list[NEREntity]:
        """Identify person entities in an OCR document."""

        entities: list[NEREntity] = []

        for page in document.pages:
            doc = self.nlp(page.text)

            for entity in doc.ents:
                if entity.label_ != "PERSON":
                    continue

                person_name = self._normalize_person_name(entity.text)

                if person_name is None:
                    continue

                ner_entity = NEREntity(
                    text=person_name,
                    label=entity.label_,
                    page_number=page.page_number,
                    start=entity.start_char,
                    end=entity.end_char,
                )

                entities.append(ner_entity)

        return entities
