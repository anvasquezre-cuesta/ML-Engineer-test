"""Fake Embedding hashing words into a small vector, for fast tests."""

from collections.abc import Sequence
import hashlib
import math

from app.domain import rag
from app.ports import embedding


class HashingEmbedding(embedding.Embedding):
    """Deterministic bag-of-words vectors; shared words mean closer texts."""

    DIMENSION = 64

    @property
    def model_name(self) -> str:
        """Returns the fake model's name.

        Returns:
            ``fake-hashing``.
        """
        return "fake-hashing"

    @property
    def dimension(self) -> int:
        """Returns the vector length.

        Returns:
            ``DIMENSION``.
        """
        return self.DIMENSION

    def embed_documents(self, texts: Sequence[str]) -> list[rag.Vector]:
        """Embeds each text.

        Args:
            texts: The passages.

        Returns:
            One unit vector per passage.
        """
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> rag.Vector:
        """Embeds one text as normalized word-hash counts.

        Args:
            text: The text.

        Returns:
            Its unit vector.
        """
        counts = [0.0] * self.DIMENSION
        for word in text.lower().split():
            digest = hashlib.sha256(word.strip(".,").encode()).digest()
            counts[digest[0] % self.DIMENSION] += 1.0
        norm = math.sqrt(sum(value * value for value in counts)) or 1.0
        return tuple(value / norm for value in counts)
