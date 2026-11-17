"""Synchronous, locally provisioned embeddings; async callers must not block the loop."""

import math
from pathlib import Path
import threading
from typing import Sequence

from app.core.embedding_model import MODEL_DIMENSIONS, MODEL_DIRECTORY, MODEL_MAX_TOKENS, verified_model_snapshot


class EmbeddingModelUnavailableError(RuntimeError):
    """The pinned local model is missing, changed, or cannot be loaded."""


class EmbeddingInputError(ValueError):
    """Embedding input is empty, too large, or would be truncated."""


class EmbeddingProcessingError(RuntimeError):
    """Embedding inference failed or returned invalid vectors."""


class EmbeddingModel:
    """Load and verify one pinned CPU model for reuse by synchronous callers."""

    def __init__(self, directory: str | Path = MODEL_DIRECTORY):
        self._snapshot = verified_model_snapshot(directory)
        try:
            snapshot = self._snapshot.__enter__()
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                str(snapshot), local_files_only=True, trust_remote_code=False, device="cpu",
            )
            if (self._model.get_embedding_dimension() != MODEL_DIMENSIONS
                    or self._model.max_seq_length != MODEL_MAX_TOKENS):
                raise ValueError("Unexpected embedding model configuration")
        except Exception:
            self._snapshot.__exit__(None, None, None)
            raise EmbeddingModelUnavailableError("The pinned embedding model is unavailable") from None
        self.tokenizer = self._model.tokenizer
        self._lock = threading.Lock()

    def close(self) -> None:
        self._snapshot.__exit__(None, None, None)

    def encode(
        self, texts: Sequence[str], *, max_tokens: int = 128, batch_size: int = 16, max_inputs: int = 1000,
        max_input_chars: int = 100_000, max_document_chars: int = 1_000_000,
    ) -> list[list[float]]:
        """Encode bounded non-empty inputs without silently truncating tokens."""
        if (not isinstance(texts, (list, tuple)) or type(max_tokens) is not int
                or type(batch_size) is not int or type(max_inputs) is not int
                or type(max_input_chars) is not int or type(max_document_chars) is not int
                or max_input_chars <= 0 or max_document_chars <= 0
                or not 1 <= max_tokens <= MODEL_MAX_TOKENS or batch_size <= 0 or max_inputs <= 0):
            raise EmbeddingInputError("Invalid embedding limits or inputs")
        if (len(texts) > max_inputs or any(not isinstance(text, str) or not text.strip() for text in texts)
                or any(len(text) > max_input_chars for text in texts)
                or sum(map(len, texts)) > max_document_chars):
            raise EmbeddingInputError("Embedding inputs are empty or exceed their limit")
        if not texts:
            return []
        with self._lock:
            try:
                special_count = len(self.tokenizer.encode("", add_special_tokens=True, truncation=False))
                tokenized = [self.tokenizer.encode(text, add_special_tokens=True, truncation=False) for text in texts]
                counts = list(map(len, tokenized))
            except Exception:
                raise EmbeddingProcessingError("Embedding tokenization failed") from None
            if any(count <= special_count or count > max_tokens for count in counts):
                raise EmbeddingInputError("An embedding input has no content tokens or exceeds the token budget")
            try:
                vectors = self._model.encode(
                    list(texts), batch_size=batch_size, show_progress_bar=False,
                    convert_to_numpy=True, normalize_embeddings=True,
                )
                result = [[float(value) for value in vector] for vector in vectors]
                if len(result) != len(texts) or any(
                    len(vector) != MODEL_DIMENSIONS
                    or not all(math.isfinite(value) for value in vector)
                    or not any(value != 0.0 for value in vector)
                    for vector in result
                ):
                    raise ValueError("Invalid embedding vectors")
                return result
            except Exception:
                raise EmbeddingProcessingError("Embedding inference failed") from None


_default_model: EmbeddingModel | None = None
_default_lock = threading.Lock()


def _get_default_model() -> EmbeddingModel:
    global _default_model
    with _default_lock:
        if _default_model is None:
            _default_model = EmbeddingModel()
        return _default_model


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Compatibility helper for synchronous callers using the local model."""
    return _get_default_model().encode(texts)


def get_query_embedding(text: str) -> list[float]:
    """Compatibility helper for future synchronous query embedding."""
    from app.core.config import get_settings
    return _get_default_model().encode([text], max_tokens=get_settings().embedding_query_max_tokens)[0]
