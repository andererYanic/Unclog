"""LLM wrapper: retries, caching, structured outputs, cost tracking, routing (brief §17).

All agents call Claude through :class:`LLMClient`; nothing else imports the SDK directly.
"""

from .client import LLMClient, StructuredOutputError
from .cost import BudgetExceeded, CostTracker
from .pricing import PRICES, ModelPrice, cost_usd
from .types import LLMRequest, LLMResponse, Usage

__all__ = [
    "PRICES",
    "BudgetExceeded",
    "CostTracker",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "ModelPrice",
    "StructuredOutputError",
    "Usage",
    "cost_usd",
]
