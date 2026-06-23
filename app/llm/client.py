"""Provider-agnostic LLM client with a single ``complete()`` method.

The rest of the app calls ``complete(...)`` without knowing which provider
answers. Today that is Groq (OpenAI-style chat completions); an Anthropic branch
slots in later by following the same shape. Every call logs token usage, latency,
and estimated cost.

``complete_structured()`` builds on ``complete()`` to return a *validated* Pydantic
object, retrying on invalid output -- the reliable-JSON path the triage step needs.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.config import LLMConfig
from app.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)

# Defaults for a single completion. A low temperature keeps triage consistent.
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2

# A Pydantic model type, used to type complete_structured()'s return value.
T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when the model never returns output matching the requested schema."""


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
        json_mode: bool = False,
    ) -> LLMResult:
        """Send one prompt and return the completion plus usage/cost/latency.

        Set ``json_mode=True`` to ask the provider to emit syntactically valid JSON
        (each provider maps this to its own native setting).
        """
        if self.config.provider == "groq":
            return self._complete_groq(prompt, system, max_tokens, temperature, json_mode)
        # Unreachable today: _build_client already rejected other providers.
        raise NotImplementedError(self.config.provider)

    def complete_structured(
        self,
        prompt: str,
        schema: type[T],
        system: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = 2,
    ) -> T:
        """Return a validated instance of ``schema``, retrying on invalid output.

        Asks the model for JSON matching ``schema``'s JSON Schema, parses and
        validates it with Pydantic, and on failure re-prompts with the error up to
        ``max_retries`` times. Raises ``StructuredOutputError`` if it never produces
        valid output. This is the reliability layer that makes model output safe to
        build on.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        instructed_system = (f"{system}\n\n" if system else "") + (
            "Respond with a single JSON object conforming exactly to this JSON Schema. "
            "Output JSON only -- no prose, no markdown fences.\n\n"
            f"Schema:\n{schema_json}"
        )

        user_prompt = prompt
        last_error: str | None = None

        for attempt in range(1, max_retries + 2):  # 1 initial try + max_retries
            result = self.complete(
                user_prompt,
                system=instructed_system,
                max_tokens=max_tokens,
                json_mode=True,
            )
            try:
                return schema.model_validate(json.loads(result.text))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)
                logger.warning(
                    "Structured output attempt %d/%d invalid: %s",
                    attempt, max_retries + 1, last_error,
                )
                # Feed the error back so the model can self-correct on the next try.
                user_prompt = (
                    f"{prompt}\n\nYour previous reply was not valid:\n{last_error}\n"
                    "Return corrected JSON only."
                )

        raise StructuredOutputError(
            f"No valid {schema.__name__} after {max_retries + 1} attempts. "
            f"Last error: {last_error}"
        )

    def _complete_groq(
        self,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> LLMResult:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Groq's "JSON mode" forces the response to be syntactically valid JSON.
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}

        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **extra,
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
