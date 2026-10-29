"""Exact-term ranking of chunks with Okapi BM25 (TRD ADR-014).

The lexical half of hybrid retrieval: it finds the chunks that share the question's
exact words — names, codes, figures — where meaning-based search is weakest. Pure and
stateless: the caller passes the chunks on every call, no index is kept.
"""

import math
from collections import Counter
from collections.abc import Sequence

from app.domain.names import normalize_name

# Standard Okapi BM25 parameters: term-frequency saturation and length normalization.
K1 = 1.5
B = 0.75


def rank_by_terms(
    question: str, documents: Sequence[tuple[str, str]], limit: int
) -> list[tuple[str, float]]:
    """Return up to ``limit`` ``(chunk_id, score)`` pairs with score > 0, best first.

    ``documents`` are ``(chunk_id, text)`` pairs. Text is tokenized with the name
    normalizer (case, accents and punctuation folded), so ``González`` matches
    ``gonzalez``. Ties keep the input order.
    """
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    terms = set(_tokens(question))
    if not terms or not documents:
        return []

    tokenized = [(chunk_id, Counter(_tokens(text))) for chunk_id, text in documents]
    lengths = [sum(counts.values()) for _, counts in tokenized]
    average_length = sum(lengths) / len(lengths) or 1.0
    idf = {term: _idf(term, tokenized) for term in terms}

    scored = []
    for (chunk_id, counts), length in zip(tokenized, lengths, strict=True):
        norm = K1 * (1 - B + B * length / average_length)
        score = sum(
            idf[term] * counts[term] * (K1 + 1) / (counts[term] + norm)
            for term in terms
            if counts[term]
        )
        if score > 0:
            scored.append((chunk_id, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)  # stable: ties keep input order
    return scored[:limit]


def _tokens(text: str) -> list[str]:
    return normalize_name(text).split()


def _idf(term: str, tokenized: list[tuple[str, Counter[str]]]) -> float:
    """Always positive, so a term present in most chunks still never lowers a score."""
    total = len(tokenized)
    containing = sum(1 for _, counts in tokenized if counts[term])
    return math.log(1 + (total - containing + 0.5) / (containing + 0.5))
