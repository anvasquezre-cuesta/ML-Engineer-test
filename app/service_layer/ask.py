"""Use case: answer a question from the ingested documents, with sources."""

import structlog

from app.domain import answering
from app.ports import cpu_runner
from app.ports import embedding
from app.ports import llm as llm_port
from app.ports import prompts as prompts_port
from app.ports import vector_store

log = structlog.stdlib.get_logger(__name__)


class AskQuestion:
    """Retrieves the closest chunks and asks the model to answer from them."""

    def __init__(
        self,
        embedder: embedding.Embedding,
        store: vector_store.VectorStore,
        prompts: prompts_port.Prompts,
        llm: llm_port.Llm,
        cpu: cpu_runner.CpuRunner,
        top_k: int,
    ) -> None:
        """Initializes the use case.

        Args:
            embedder: Embeds the question.
            store: Finds the chunks closest to the question.
            prompts: Renders the grounded prompt.
            llm: Writes the answer.
            cpu: Runs the blocking embedding call.
            top_k: Chunks shown to the model.
        """
        self._embedder = embedder
        self._store = store
        self._prompts = prompts
        self._llm = llm
        self._cpu = cpu
        self._top_k = top_k

    async def __call__(  # noqa: DOC501, DOC503
        self, question: str
    ) -> answering.Answer:
        """Answers ``question`` from the retrieved chunks only.

        With nothing retrieved the model is not called and the answer is the
        refusal. An answer that cites no shown passage lists every retrieved
        chunk, and a warning is logged.

        Args:
            question: The user's question.

        Returns:
            The answer and the retrieved chunks it rests on.
        """
        raise NotImplementedError
