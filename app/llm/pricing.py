"""Token pricing tables and cost estimation, keyed by (provider, model).

Prices are USD per 1,000,000 tokens, taken from each provider's public rate card.
This is used only for observability/logging: on a free tier the real charge may be
$0, but logging the would-be cost makes spend visible the moment you switch tiers
or providers. Update the table from the provider's rate card as prices change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenPrice:
    """USD per 1,000,000 tokens."""

    input_per_1m: float
    output_per_1m: float


# (provider, model) -> price.
PRICES: dict[tuple[str, str], TokenPrice] = {
    # Groq (https://groq.com/pricing)
    ("groq", "llama-3.3-70b-versatile"): TokenPrice(0.59, 0.79),
    ("groq", "openai/gpt-oss-120b"): TokenPrice(0.15, 0.60),
    ("groq", "openai/gpt-oss-20b"): TokenPrice(0.075, 0.30),
    ("groq", "llama-3.1-8b-instant"): TokenPrice(0.05, 0.08),
    # Anthropic (ready for when that provider is wired up)
    ("anthropic", "claude-opus-4-8"): TokenPrice(5.0, 25.0),
    ("anthropic", "claude-sonnet-4-6"): TokenPrice(3.0, 15.0),
    ("anthropic", "claude-haiku-4-5"): TokenPrice(1.0, 5.0),
}


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Estimate the USD cost of a call, or ``None`` if the model's price is unknown.

    Returning ``None`` (rather than 0.0) keeps "we don't know" distinct from
    "it's free" -- the caller can log it honestly instead of guessing.
    """
    price = PRICES.get((provider, model))
    if price is None:
        return None
    return (
        input_tokens / 1_000_000 * price.input_per_1m
        + output_tokens / 1_000_000 * price.output_per_1m
    )
