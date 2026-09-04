import re
import unicodedata

from thefuzz import fuzz

from app.models.schemas import FuzzyMatch, NamePair


def normalize(text: str) -> str:
    """'María  GONZÁLEZ,' -> 'maria gonzalez'. Accents, case and punctuation are OCR noise.

    Apostrophes and hyphens are removed rather than turned into spaces so "O'Brien" and
    "Jean-Luc" stay single tokens, matching how tesseract emits them.
    """
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    stripped = re.sub(r"['’`\-]", "", stripped)
    stripped = re.sub(r"[^\w\s]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip().casefold()


def similarity(a: str, b: str) -> float:
    """Full-string ratio in 0..1. Not partial_ratio: that scores 'Ann' vs 'Annabelle' as 1.0."""
    return fuzz.ratio(normalize(a), normalize(b)) / 100


def match_names(
    extracted: list[str], requested: list[NamePair], threshold: float
) -> list[FuzzyMatch]:
    matches = []
    for name in extracted:
        best_score, best_pair = 0.0, None
        for pair in requested:
            full = f"{pair.first_name} {pair.last_name}"
            # documents sometimes print "Last First"; take whichever order fits
            reversed_ = f"{pair.last_name} {pair.first_name}"
            score = max(similarity(name, full), similarity(name, reversed_))
            if score > best_score:
                best_score, best_pair = score, full
        if best_pair is not None and best_score >= threshold:
            matches.append(
                FuzzyMatch(extracted_name=name, matched_name=best_pair, score=round(best_score, 3))
            )
    return matches
