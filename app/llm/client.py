"""Provider-agnostic LLM client with a single ``complete()`` method.

The rest of the app calls ``complete(...)`` without knowing which provider
answers. Today that is Groq (OpenAI-style chat completions); an Anthropic branch
slots in later by following the same shape. Every call logs token usage, latency,
and estimated cost.
"""

import logging
import time
from dataclasses import dataclass

from app.llm.config import LLMConfig
from app.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)

# Defaults for a single completion. A low temperature keeps triage consistent.
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2


@dataclass(frozen=True)
class LLMResult:
    """The model's text plus the observability data for the call."""

    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float | None  # None when the model has no entry in the price table


class LLMClient:
    """A thin, provider-agnostic wrapper over a chat-completions API."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = self._build_client(config)

    @staticmethod
    def _build_client(config: LLMConfig):
        """Construct the underlying provider SDK client (fails fast on bad config)."""
        if config.provider == "groq":
            from groq import Groq  # imported lazily so other setups needn't install it

            return Groq(api_key=config.api_key)
        if config.provider == "anthropic":
            raise NotImplementedError(
                "The 'anthropic' provider isn't wired up yet -- add it here when needed."
            )
        raise ValueError(f"Unsupported provider: {config.provider!r}")

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> LLMResult:
        """Send one prompt and return the completion plus usage/cost/latency."""
        if self.config.provider == "groq":
            return self._complete_groq(prompt, system, max_tokens, temperature)
        # Unreachable today: _build_client already rejected other providers.
        raise NotImplementedError(self.config.provider)

    def _complete_groq(
        self,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_s = time.perf_counter() - start

        text = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        cost_usd = estimate_cost(
            self.config.provider, self.config.model, input_tokens, output_tokens
        )

        result = LLMResult(
            text=text,
            provider=self.config.provider,
            model=self.config.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency_s,
            cost_usd=cost_usd,
        )
        self._log(result)
        return result

    @staticmethod
    def _log(result: LLMResult) -> None:
        cost = "unknown" if result.cost_usd is None else f"${result.cost_usd:.6f}"
        logger.info(
            "LLM call provider=%s model=%s in_tokens=%d out_tokens=%d latency=%.2fs cost=%s",
            result.provider,
            result.model,
            result.input_tokens,
            result.output_tokens,
            result.latency_s,
            cost,
        )
