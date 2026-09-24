"""Ask against an in-memory Qdrant with a scripted model."""

import qdrant_client

from app import config
from app.adapters.langchain_prompts import prompts
from app.adapters.qdrant import vector_store as qdrant_store
from app.domain import rag
from app.service_layer import ask
from tests.fakes import cpu_runner
from tests.fakes import embedding
from tests.fakes import llm as llm_fake

HIRING = "Anna Berg will lead hiring for the data team starting in March."
BUDGET = "The board approved the laboratory budget for next year."


async def store_with(*texts: str) -> qdrant_store.QdrantVectorStore:
    """Returns an in-memory store holding one page-0 chunk per text.

    Args:
        *texts: Chunk texts, stored as chunks 0, 1, ... of ``memo.pdf``.

    Returns:
        The store.
    """
    store = qdrant_store.QdrantVectorStore(
        qdrant_client.AsyncQdrantClient(location=":memory:"),
        config.QdrantSettings(),
        collection="chunks_test",
        dimension=embedding.HashingEmbedding.DIMENSION,
    )
    await store.ensure_collection()
    embedder = embedding.HashingEmbedding()
    await store.upsert(
        [
            rag.EmbeddedChunk(
                rag.Chunk("memo.pdf", "h", 0, i, 0, len(t), t, "sentence"),
                embedder.embed_query(t),
            )
            for i, t in enumerate(texts)
        ]
    )
    return store


def asker(
    store: qdrant_store.QdrantVectorStore, model: llm_fake.ScriptedLlm
) -> ask.AskQuestion:
    """Builds the use case with the shipped prompt files.

    Args:
        store: The vector store.
        model: The scripted model.

    Returns:
        The use case.
    """
    return ask.AskQuestion(
        embedder=embedding.HashingEmbedding(),
        store=store,
        prompts=prompts.LangChainPrompts(config.PromptSettings().directory),
        llm=model,
        cpu=cpu_runner.InlineCpuRunner(),
        top_k=2,
    )


async def test_empty_store_refuses_without_calling_the_model() -> None:
    model = llm_fake.ScriptedLlm("Anna Berg [1].")
    shipped = prompts.LangChainPrompts(config.PromptSettings().directory)

    answer = await asker(await store_with(), model)("Who leads hiring?")

    assert (answer.text, answer.sources, answer.refused) == (
        shipped.refusal,
        (),
        True,
    )
    assert model.prompts == []


async def test_citation_resolves_to_the_retrieved_chunk_shown_first() -> None:
    model = llm_fake.ScriptedLlm("Anna Berg leads hiring [1].")
    store = await store_with(BUDGET, HIRING)

    answer = await asker(store, model)(HIRING)

    assert answer.sources == ("memo.pdf#page=1&chunk=1",)
    assert HIRING in model.prompts[0].user
