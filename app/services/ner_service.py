import re

import spacy

# spaCy's English models say PERSON; the multilingual ones say PER
PERSON_LABELS = {"PERSON", "PER"}


class SpacyNer:
    def __init__(self, model: str):
        self.nlp = spacy.load(model, disable=["lemmatizer", "parser"])

    def person_names(self, text: str) -> list[str]:
        names: list[str] = []
        for ent in self.nlp(text).ents:
            if ent.label_ in PERSON_LABELS:
                name = clean_name(ent.text)
                if name:
                    names.append(name)
        return names


def clean_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw).strip(" \t\n.,;:()[]\"'")
    name = re.sub(r"['’]s$", "", name)
    # OCR junk that spaCy still tags as a person: numbers, single letters, empty
    if len(name) < 2 or any(ch.isdigit() for ch in name):
        return ""
    return name
