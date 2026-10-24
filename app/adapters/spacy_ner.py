"""spaCy NER adapter — implements the NerProvider port; person names only."""

import spacy

from app.services.ner_service import NerProvider


class SpacyNer:
    def __init__(self, model_name: str) -> None:
        self.nlp = spacy.load(model_name)

    def extract_persons(self, text: str) -> list[str]:
        doc = self.nlp(text)
        return [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
