"""``Embedder`` backed by sentence-transformers.

Vectors are L2-normalised, so cosine similarity is a dot product and Chroma's
cosine distance maps to similarity as ``1 - distance``.

The model silently truncates inputs longer than ``max_seq_length`` word pieces
(256 for all-MiniLM-L6-v2, special tokens included). Chunks are sized in words,
and the samples measured 1.27-1.51 pieces per word, so a dense chunk could cross
the limit: each truncated chunk is counted and logged instead of ignored.
"""

from collections.abc import Sequence

import structlog
from sentence_transformers import SentenceTransformer

from app.core.config import RAGSettings

logger = structlog.get_logger(__name__)


class SentenceTransformerEmbedder:
    def __init__(self, settings: RAGSettings) -> None:
        self._model = SentenceTransformer(settings.embedding_model, device="cpu")
        self._batch_size = settings.embedding_batch_size
        self.max_tokens: int | None = self._model.max_seq_length  # None: model has no limit

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._warn_if_truncated(texts)
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(v) for v in row] for row in vectors]

    def _warn_if_truncated(self, texts: Sequence[str]) -> None:
        if self.max_tokens is None:
            return
        lengths = [len(ids) for ids in self._model.tokenizer(list(texts))["input_ids"]]
        truncated = sum(n > self.max_tokens for n in lengths)
        if truncated:
            logger.warning(
                "embedding_input_truncated",
                truncated_chunks=truncated,
                longest_tokens=max(lengths),
                max_tokens=self.max_tokens,
            )
