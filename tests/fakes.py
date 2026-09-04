"""Stand-ins for the heavy bits so the pipelines run in milliseconds."""

from app.models.domain import Page, RetrievedChunk, Word


def page_from_lines(index: int, lines: list[str], width=612.0, height=792.0) -> Page:
    """Lay words out on a fake page: each word 40pt wide, each line 20pt tall."""
    words = []
    for li, line in enumerate(lines):
        for wi, token in enumerate(line.split()):
            words.append(
                Word(
                    text=token, x=50 + wi * 45, y=50 + li * 20, width=40, height=12, line=(1, 1, li)
                )
            )
    return Page(index=index, width=width, height=height, words=words)


class FakeOcr:
    def __init__(self, pages: list[Page]):
        self.pages = pages
        self.calls = 0

    def run(self, pdf: bytes) -> list[Page]:
        self.calls += 1
        return self.pages


class FakeNer:
    def __init__(self, names: list[str]):
        self.names = names

    def person_names(self, text: str) -> list[str]:
        return [n for n in self.names if n in text]


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in texts]


class InMemoryStore:
    def __init__(self):
        self.rows: dict[str, tuple[str, str]] = {}

    def add(self, ids, texts, embeddings, sources) -> None:
        for id_, text, source in zip(ids, texts, sources, strict=True):
            self.rows[id_] = (text, source)

    def query(self, embedding, top_k) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(text=t, source=s, score=1.0) for t, s in list(self.rows.values())[:top_k]
        ]

    def ping(self) -> None:
        pass


class FakeLLM:
    def __init__(self, answer="the answer"):
        self.answer = answer
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.prompts.append((system, user))
        return self.answer
