"""Per-run cost accounting and budget enforcement (brief §17: per-run budgets enforced)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """Raised before a call when the run budget is already spent."""


@dataclass
class CostTracker:
    budget_usd: float | None = None
    total_usd: float = 0.0
    calls: int = 0
    by_agent: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    def check(self) -> None:
        if self.budget_usd is not None and self.total_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"Run budget ${self.budget_usd:.2f} exhausted (spent ${self.total_usd:.4f})"
            )

    def record(self, agent: str, usd: float) -> None:
        self.total_usd += usd
        self.calls += 1
        self.by_agent[agent] += usd

    def summary(self) -> dict[str, object]:
        return {
            "total_usd": round(self.total_usd, 6),
            "calls": self.calls,
            "budget_usd": self.budget_usd,
            "by_agent": {k: round(v, 6) for k, v in sorted(self.by_agent.items())},
        }
