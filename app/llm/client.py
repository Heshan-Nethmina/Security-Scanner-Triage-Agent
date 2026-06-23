"""Provider-agnostic LLM client.

- ``complete()``           -- one prompt -> text (+ usage/cost logging)
- ``complete_structured()`` -- one prompt -> validated Pydantic object (validate + retry)
- ``chat()``              -- one tool-enabled turn over a message list; the building
                            block for the agent loop (returns text and/or tool calls)

Today the provider is Groq (OpenAI-style chat completions); an Anthropic branch
slots in by following the same shape. Every model call logs token usage, latency,
and estimated cost.
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


@dataclass(frozen=True)
class ToolCall:
    """A normalized request from the model to run one tool."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatTurn:
    """The outcome of one tool-enabled turn.

    If ``tool_calls`` is non-empty, the model wants those tools run before it will
    answer. ``assistant_message`` is the assistant turn to append verbatim to the
    running transcript so the next request stays coherent.
    """

    text: str | None
    tool_calls: list[ToolCall]
    assistant_message: dict
    usage: LLMResult


@dataclass
class UsageStats:
    """Running totals across all calls made by one client (observability)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0     # sums known per-call costs; unknown prices count as 0
    latency_s: float = 0.0

    def add(self, result: "LLMResult") -> None:
        self.calls += 1
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.cost_usd += result.cost_usd or 0.0
        self.latency_s += result.latency_s


class LLMClient:
    """A thin, provider-agnostic wrapper over a chat-completions API."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client = self._build_client(config)
        self.usage = UsageStats()  # accumulates across every call this client makes

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

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> ChatTurn:
        """Run one turn over a message list, optionally offering ``tools``.

        Returns a ``ChatTurn``: the model's text and/or its tool-call requests, plus
        the assistant message to append to the transcript. This is what the agent
        loop calls repeatedly.
        """
        if self.config.provider == "groq":
            return self._chat_groq(messages, tools, max_tokens, temperature)
        raise NotImplementedError(self.config.provider)

    # --- Groq-specific implementations -------------------------------------------

    def _complete_groq(
        self,
        prompt: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> LLMResult:
        messages: list[dict] = []
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
        return self._make_result(text, response.usage, latency_s)

    def _chat_groq(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        max_tokens: int,
        temperature: float,
    ) -> ChatTurn:
        extra: dict = {}
        if tools:
            extra["tools"] = tools
            extra["tool_choice"] = "auto"  # let the model decide whether to call one

        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **extra,
        )
        latency_s = time.perf_counter() - start
        msg = response.choices[0].message
        usage = self._make_result(msg.content or "", response.usage, latency_s)

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (msg.tool_calls or [])
        ]

        # Rebuild the assistant turn explicitly so we control exactly what we echo
        # back (OpenAI/Groq accept this shape; content may be null with tool calls).
        assistant_message: dict = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]

        return ChatTurn(
            text=msg.content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=usage,
        )

    # --- shared helpers ----------------------------------------------------------

    def _make_result(self, text: str, usage, latency_s: float) -> LLMResult:
        """Build an LLMResult from a provider usage object and log it."""
        result = LLMResult(
            text=text,
            provider=self.config.provider,
            model=self.config.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_s=latency_s,
            cost_usd=estimate_cost(
                self.config.provider, self.config.model,
                usage.prompt_tokens, usage.completion_tokens,
            ),
        )
        self.usage.add(result)
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
