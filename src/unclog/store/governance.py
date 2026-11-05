"""Per-client governance: policy, retention, persistent cost budget, model-call audit (§14, §17).

``clients/<id>/policy.json`` holds the client's settings::

    {"raw_days": 90, "derived_days": 365, "max_usd": 50.0}
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..llm.cost import BudgetExceeded, CostTracker
from .client_store import ClientStore


@dataclass
class ClientPolicy:
    raw_days: int = 90
    derived_days: int = 365
    max_usd: float | None = None

    @staticmethod
    def load(store: ClientStore) -> ClientPolicy:
        p = Path(store.root) / "policy.json"
        return ClientPolicy(**json.loads(p.read_text())) if p.exists() else ClientPolicy()

    def save(self, store: ClientStore, actor: str) -> None:
        (Path(store.root) / "policy.json").write_text(json.dumps(asdict(self), indent=2))
        store._audit("policy_set", actor, **asdict(self))


def apply_retention(
    store: ClientStore, actor: str, now: float | None = None, dry_run: bool = True
) -> list[str]:
    """Delete raw uploads older than ``raw_days`` and derived run files (pipeline checkpoints,
    system run outputs, decided outbox items) older than ``derived_days``. Review logs, the audit
    log, the results ledger and approved deliverables are kept (they are the record)."""
    pol = ClientPolicy.load(store)
    now = now or time.time()
    root = Path(store.root)
    targets: list[Path] = []
    for f in (root / "raw").glob("*"):
        if f.is_file() and now - f.stat().st_mtime > pol.raw_days * 86400:
            targets.append(f)
    derived = [*(root / "pipeline").glob("*.json"), *(root / "systems").glob("*/v*/runs/*/*")]
    for f in (root / "outbox").glob("ob-*.json"):
        if json.loads(f.read_text()).get("status") in ("executed", "rejected", "failed"):
            derived.append(f)
    targets += [
        f for f in derived if f.is_file() and now - f.stat().st_mtime > pol.derived_days * 86400
    ]
    rel = sorted(str(f.relative_to(root)) for f in targets)
    if not dry_run:
        for f in targets:
            f.chmod(0o640)
            f.unlink()
        store._audit(
            "retention_apply",
            actor,
            deleted=len(rel),
            raw_days=pol.raw_days,
            derived_days=pol.derived_days,
        )
    return rel


class EngagementBudget(CostTracker):
    """CostTracker that persists spend per client across runs and enforces ``max_usd``."""

    def __init__(self, store: ClientStore, run_budget_usd: float | None = None) -> None:
        self.store = store
        self.path = Path(store.root) / "costs.jsonl"
        pol = ClientPolicy.load(store)
        super().__init__(budget_usd=run_budget_usd)
        self.engagement_max = pol.max_usd
        self.previous = (
            sum(json.loads(x)["usd"] for x in self.path.read_text().splitlines() if x.strip())
            if self.path.exists()
            else 0.0
        )

    def check(self) -> None:
        super().check()
        if (
            self.engagement_max is not None
            and self.previous + self.total_usd >= self.engagement_max
        ):
            raise BudgetExceeded(
                f"engagement budget ${self.engagement_max:.2f} for {self.store.client_id} "
                f"exhausted (spent ${self.previous + self.total_usd:.4f})"
            )

    def record(self, agent: str, usd: float) -> None:
        super().record(agent, usd)
        with self.path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "agent": agent, "usd": round(usd, 6)}) + "\n")


def audit_hook(store: ClientStore):
    """LLMClient ``on_call`` hook: every model call goes to the client audit log (no content)."""

    def hook(request, response) -> None:
        store._audit(
            "model_call",
            request.agent,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=round(response.cost_usd, 6),
            cached=response.from_cache,
            request_key=request.cache_key()[:16],
        )

    return hook
