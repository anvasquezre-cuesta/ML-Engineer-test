"""Fake SparseEmbedding counting hashed words, for fast tests."""

import collections
from collections.abc import Sequence
import hashlib

from app.domain import rag
from app.ports import sparse_embedding


class WordCountSparseEmbedding(sparse_embedding.SparseEmbedding):
    """Deterministic term counts; the same word always has the same id."""

    @property
    def model_name(self) -> str:
        """Returns the fake model's name.

        Returns:
            ``fake-word-count``.
        """
        return "fake-word-count"

    def embed_documents(self, texts: Sequence[str]) -> list[rag.SparseVector]:
        """Counts the words of each text.

        Args:
            texts: The passages.

        Returns:
            One sparse vector per passage.
        """
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> rag.SparseVector:
        """Counts the words of one text under stable hashed ids.

        Args:
            text: The text.

        Returns:
            Its word counts.
        """
        counts = collections.Counter(
            int.from_bytes(
                hashlib.sha256(word.strip(".,").encode()).digest()[:3]
            )
            for word in text.lower().split()
        )
        ids = sorted(counts)
        return rag.SparseVector(
            indices=tuple(ids), values=tuple(float(counts[i]) for i in ids)
        )
