"""`Embedder` adapter: sentence-transformers on CPU (TRD ADR-009).

e5 models need a ``passage: `` / ``query: `` prefix; it is applied here so the
application never knows about it. Vectors are normalized (cosine = dot product).
"""

import logging
from collections.abc import Sequence

from sentence_transformers import SentenceTransformer

from app.domain.errors import EmbeddingModelUnavailable

PASSAGE_PREFIX = "passage: "
QUESTION_PREFIX = "query: "


class SentenceTransformerEmbedder:
    """Loads the model once; embeds passages and questions; counts tokens."""

    def __init__(self, model_name: str) -> None:
        # Counting a long block warns "sequence length is longer than…" on every call;
        # the chunker only counts to compare with the budget, so the warning is noise.
        logging.getLogger("transformers").setLevel(logging.ERROR)
        try:
            self._model = SentenceTransformer(model_name, device="cpu")
        except (OSError, ValueError) as exc:
            raise EmbeddingModelUnavailable(f"Cannot load embedding model {model_name}") from exc

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(list(texts), PASSAGE_PREFIX)

    def embed_question(self, text: str) -> list[float]:
        return self._encode([text], QUESTION_PREFIX)[0]

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer.encode(text, add_special_tokens=False))

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        vectors = self._model.encode(texts, prompt=prefix, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]
