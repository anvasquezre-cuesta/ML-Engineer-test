from sentence_transformers import SentenceTransformer


class SentenceTransformerEmbedder:
    def __init__(self, model: str):
        self.model = SentenceTransformer(model)  # loaded once, at startup

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()
