"""`AnswerGenerator` adapter: any OpenAI-compatible chat endpoint (TRD ADR-010).

Groq by default. Timeouts and retries (exponential backoff on 408/409/429/5xx,
honouring ``Retry-After``) are the openai SDK's own; its exceptions are translated here
and never leave the adapter. The API key is never logged nor put in an error message.
"""

import httpx2
import openai

from app.domain.errors import LlmNotConfigured, LlmRateLimited, LlmTimeout, LlmUnavailable
from app.domain.grounding import LlmReply, Prompt


class OpenAiCompatibleAnswerGenerator:
    """Sends the prompt at temperature 0 and returns the text with the reported usage."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        http_client: httpx2.Client | None = None,  # the SDK's injection point; tests only
    ) -> None:
        self._model = model
        # The SDK refuses to build a client without a key; no key = not configured.
        self._client = (
            openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
                max_retries=max_retries,
                http_client=http_client,
            )
            if api_key
            else None
        )

    def generate(self, prompt: Prompt) -> LlmReply:
        if self._client is None:
            raise LlmNotConfigured("No LLM API key is configured (DOCINTEL_LLM_API_KEY)")
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                temperature=0,
            )
        except openai.APITimeoutError as exc:  # before APIConnectionError, its parent
            raise LlmTimeout("The LLM did not answer in time") from exc
        except openai.RateLimitError as exc:
            raise LlmRateLimited("The LLM provider is rate-limiting requests") from exc
        except openai.APIStatusError as exc:
            raise LlmUnavailable(f"The LLM provider failed (HTTP {exc.status_code})") from exc
        except openai.APIError as exc:
            raise LlmUnavailable("The LLM provider could not be reached") from exc
        usage = response.usage
        return LlmReply(
            text=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
