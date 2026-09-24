"""DeepEval judge backed by the service's LangChain Bedrock model builder."""

import asyncio
from typing import Any
from typing import cast

from deepeval.models import base_model
from langchain_core.language_models import chat_models as lc_chat_models

from app import config
from app.adapters.langchain_llm import chat_models

FAMILIES = ("anthropic", "amazon", "openai", "meta", "mistral")


class JudgeBudgetExceededError(Exception):
    """The evaluation used every judge call it was allowed."""


def family(model_id: str) -> str:
    """Names the vendor family of a Bedrock or OpenAI model id.

    Args:
        model_id: E.g. ``us.amazon.nova-lite-v1:0`` or ``gpt-6-luna``.

    Returns:
        The family, or the model id itself when it is not recognised.
    """
    lowered = model_id.lower()
    if lowered.startswith("gpt"):
        return "openai"
    return next((name for name in FAMILIES if name in lowered), lowered)


class Judge(base_model.DeepEvalBaseLLM):
    """Grades answers with a chat model and stops at a call budget.

    Attributes:
        calls: Judge calls made so far.
    """

    def __init__(
        self, chat: lc_chat_models.BaseChatModel, name: str, budget: int
    ) -> None:
        """Initializes the judge.

        Args:
            chat: The judge chat model, with explicit credentials.
            name: Its model id, shown in reports.
            budget: Judge calls allowed.
        """
        self._chat = chat
        self._name = name
        self._budget = budget
        self.calls = 0
        super().__init__(model=name)

    @classmethod
    def for_settings(cls, settings: config.Settings) -> "Judge":
        """Builds the judge from the service settings.

        It reuses the Bedrock credentials of the generator and refuses a
        judge from the generator's own model family, which would grade its
        own style favourably.

        Args:
            settings: The service configuration.

        Returns:
            The judge.

        Raises:
            ValueError: If judge and generator share a family.
        """
        generator = (
            settings.llm.bedrock_model
            if settings.llm.provider == "bedrock"
            else settings.llm.openai_model
        )
        if family(generator) == family(settings.eval.judge_model):
            raise ValueError(
                f"Judge {settings.eval.judge_model} and generator {generator} "
                "share a model family."
            )
        judge_settings = settings.llm.model_copy(
            update={
                "provider": "bedrock",
                "bedrock_model": settings.eval.judge_model,
                "temperature": 0.0,
            }
        )
        return cls(
            chat_models.build_chat_model(judge_settings),
            settings.eval.judge_model,
            settings.eval.max_judge_calls,
        )

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        """Returns the wrapped chat model.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Returns:
            The chat model.
        """
        return self._chat

    def generate(self, prompt: str, schema: Any = None) -> Any:
        """Grades synchronously.

        Args:
            prompt: DeepEval's grading prompt.
            schema: The pydantic model DeepEval expects, if any.

        Returns:
            The parsed schema, or the text.
        """
        return asyncio.run(self.a_generate(prompt, schema=schema))

    async def a_generate(self, prompt: str, schema: Any = None) -> Any:
        """Grades one prompt within the call budget.

        Args:
            prompt: DeepEval's grading prompt.
            schema: The pydantic model DeepEval expects, if any.

        Returns:
            The parsed schema, or the text.

        Raises:
            JudgeBudgetExceededError: If the budget is spent.
            ValueError: If the judge's output does not fit ``schema``.
        """
        if self.calls >= self._budget:
            raise JudgeBudgetExceededError(
                f"All {self._budget} judge calls are spent."
            )
        self.calls += 1
        if schema is None:
            reply = await self._chat.ainvoke(prompt)
            return reply.content
        out = cast(
            dict[str, Any],
            await self._chat.with_structured_output(
                schema, include_raw=True
            ).ainvoke(prompt),
        )
        if out["parsed"] is None:
            raise ValueError(f"Unparsed judge output: {out['parsing_error']}")
        return out["parsed"]

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        """Returns the judge's model id.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Returns:
            The model id.
        """
        return self._name
