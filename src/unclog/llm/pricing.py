"""Model price table (USD per million tokens) for cost tracking.

Source: Anthropic first-party API list prices as of 2026-10. Re-check when adding models; prices
are config, not code, so update here and record the change in docs/decisions/.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import Usage


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    # 5-minute cache writes bill at 1.25x base input.
    cache_write_multiplier: float = 1.25

    @property
    def cache_write(self) -> float:
        return self.input * self.cache_write_multiplier


PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-1": ModelPrice(input=10.00, output=50.00, cache_read=0.25),
    "claude-opus-5-5": ModelPrice(input=4.00, output=20.00, cache_read=0.20),
    "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_read=0.20),
    # Haiku 5.5: prompts <=100K tokens; cache-read assumed at 0.1x input.
    "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_read=0.01),
}

_PER = 1_000_000


def cost_usd(model: str, usage: Usage) -> float:
    """Deterministic cost of one call. Unknown models raise rather than silently costing $0."""
    try:
        p = PRICES[model]
    except KeyError as exc:
        raise KeyError(
            f"No price for model {model!r}; add it to unclog.llm.pricing.PRICES"
        ) from exc
    return (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_input_tokens * p.cache_read
        + usage.cache_creation_input_tokens * p.cache_write
    ) / _PER
