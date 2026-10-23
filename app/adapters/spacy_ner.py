"""``NERModel`` backed by spaCy.

Only the ``ner`` component is enabled. In the ``en_core_web_*`` pipelines it has
its own embedding layer (only the tagger and parser listen to the shared
``tok2vec``), so the entities are identical to the full pipeline at a fraction
of the cost. English models label people ``PERSON``, Spanish and multilingual
ones ``PER``; both map to one meaning through ``NER__PERSON_LABELS``.
"""

from collections.abc import Sequence

import spacy

from app.core.config import NERSettings
from app.domain.models import EntitySpan


class SpacyNER:
    def __init__(self, settings: NERSettings) -> None:
        try:
            self._nlp = spacy.load(settings.model, enable=["ner"])
        except OSError as exc:
            raise RuntimeError(
                f"spaCy model '{settings.model}' is not installed; run `uv sync`."
            ) from exc
        self._person_labels = frozenset(settings.person_labels)

    def find_persons(self, texts: Sequence[str]) -> list[list[EntitySpan]]:
        return [
            [
                EntitySpan(text=ent.text, start_char=ent.start_char, end_char=ent.end_char)
                for ent in doc.ents
                if ent.label_ in self._person_labels
            ]
            for doc in self._nlp.pipe(texts)
        ]
