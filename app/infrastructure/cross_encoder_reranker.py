"""`Reranker` adapter: a sentence-transformers cross-encoder on CPU (TRD ADR-014).

Scores are the model's raw outputs (logits for the default mmarco model); the relevance
gate threshold is calibrated on that scale, so nothing is rescaled here.
"""

from collections.abc import Sequence

from sentence_transformers import CrossEncoder

from app.domain.errors import RerankerUnavailable


class CrossEncoderReranker:
    """Loads the cross-encoder once and scores (question, passage) pairs."""

    def __init__(self, model_name: str) -> None:
        try:
            self._model = CrossEncoder(model_name, device="cpu")
        except (OSError, ValueError) as exc:
            raise RerankerUnavailable(f"Cannot load reranker model {model_name}") from exc

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        scores = self._model.predict([(question, text) for text in texts])
        return [float(value) for value in scores]
