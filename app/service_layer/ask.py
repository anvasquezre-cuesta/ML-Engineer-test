"""Use case: answer a question from the ingested documents, with sources."""

import structlog

from app.domain import answering
from app.domain import rag
from app.ports import cpu_runner
from app.ports import embedding
from app.ports import llm as llm_port
from app.ports import prompts as prompts_port
from app.ports import sparse_embedding
from app.ports import vector_store

log = structlog.stdlib.get_logger(__name__)


class AskQuestion:
    """Retrieves the closest chunks and asks the model to answer from them."""

    def __init__(
        self,
        embedder: embedding.Embedding,
        sparse_embedder: sparse_embedding.SparseEmbedding,
        store: vector_store.VectorStore,
        prompts: prompts_port.Prompts,
        llm: llm_port.Llm,
        cpu: cpu_runner.CpuRunner,
        top_k: int,
    ) -> None:
        """Initializes the use case.

        Args:
            embedder: Embeds the question.
            sparse_embedder: Weights the question's terms.
            store: Finds the best chunks by hybrid search.
            prompts: Renders the grounded prompt.
            llm: Writes the answer.
            cpu: Runs the blocking embedding calls.
            top_k: Chunks shown to the model.
        """
        self._embedder = embedder
        self._sparse_embedder = sparse_embedder
        self._store = store
        self._prompts = prompts
        self._llm = llm
        self._cpu = cpu
        self._top_k = top_k

    async def __call__(self, question: str) -> answering.Answer:
        """Answers ``question`` from the retrieved chunks only.

        With nothing retrieved the model is not called and the answer is the
        refusal. An answer that cites no shown passage lists every retrieved
        chunk, and a warning is logged.

        Args:
            question: The user's question.

        Returns:
            The answer and the retrieved chunks it rests on.
        """
        query = rag.SearchQuery(
            dense=await self._cpu.run(self._embedder.embed_query, question),
            sparse=await self._cpu.run(
                self._sparse_embedder.embed_query, question
            ),
        )
        hits = await self._store.hybrid_search(query, self._top_k)
        if not hits:
            return answering.refused(self._prompts.refusal)
        chunks = [hit.chunk for hit in hits]
        prompt = self._prompts.answer(question, answering.passages(chunks))
        completion = await self._llm.complete(prompt)
        answer = answering.read_answer(
            completion, chunks, self._prompts.refusal
        )
        if not answer.refused and not answer.cited:
            log.warning("ask.uncited_answer", chunks=len(chunks))
        return answer
