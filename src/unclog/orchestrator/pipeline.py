"""Orchestrated, resumable engagement pipeline (brief §6, §16).

Phases (explicit, in order):
  diagnose        0-4  ingest raw files, flow, heat table, constraint, policy audit
  goal_factoring  5    LLM, checkpointed
  opportunities   6    LLM, checkpointed; Critic runs after it
  feasibility     7    deterministic
  plan            8    value model (if effects are given) + roadmap
  report          14   deliverables as drafts -> stop for human review

Gates run after every phase; a blocking gate stops the run with its reason. LLM phases are
checkpointed in ``clients/<id>/pipeline/<phase>.json`` with a hash of their inputs, so a resumed
run reuses paid-for results unless the inputs changed. If the Critic blocks, the phase is re-run
once; a second block escalates to a human (brief §16). Build/deploy (phases 9-10) are not
automatic: they need a human go-live decision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..agents.base import AgentEscalation
from ..build.library import by_id
from ..evals.cases import SyntheticCase
from ..evals.runner import run_case
from ..goalfactor import GoalTree
from ..llm import LLMClient
from ..qa.critic import critique
from ..qa.gates import GateResult, run_gates
from ..reporting import Bundle, plan, write
from ..schemas.design import FindingSeverity, GoalNode, Opportunity, Risk
from ..scoring.feasibility import assess
from ..scoring.value import Economics, OpportunityInput, SimSettings, value_portfolio
from ..store import ClientStore
from .state import State

REGULATED_DOMAINS = {"hr", "finance", "legal"}

PHASE_GATES: dict[str, tuple[set[str], set[str]]] = {
    # phase: (gates to run, gates that block)
    "diagnose": ({"G1", "G2", "G3", "G4", "G5", "G17"}, {"G1", "G3"}),
    "goal_factoring": ({"G1", "G4", "G16"}, {"G1", "G4"}),
    "opportunities": ({"G1", "G4", "G6", "G8", "G12", "G16"}, {"G1", "G6", "G8", "G12"}),
    "feasibility": ({"G1"}, {"G1"}),
    "plan": ({"G7", "G9", "G10", "G17"}, {"G7", "G9", "G10"}),
    "report": ({f"G{i}" for i in range(1, 18)}, set()),
}


@dataclass
class PipelineRun:
    state: State
    gates: dict[str, list[GateResult]] = field(default_factory=dict)
    status: str = "running"  # running | stopped | escalated | awaiting_review
    reason: str = ""
    human_review: list[str] = field(default_factory=list)
    report_paths: list[Path] = field(default_factory=list)


class Checkpoints:
    def __init__(self, store: ClientStore | None) -> None:
        self.dir = Path(store.root) / "pipeline" if store else None
        if self.dir:
            self.dir.mkdir(exist_ok=True)

    @staticmethod
    def key(*parts: object) -> str:
        raw = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def load(self, phase: str, key: str) -> dict | None:
        if not self.dir:
            return None
        p = self.dir / f"{phase}.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return d["payload"] if d.get("key") == key else None

    def save(self, phase: str, key: str, payload: dict) -> None:
        if self.dir:
            (self.dir / f"{phase}.json").write_text(
                json.dumps(
                    {"key": key, "payload": payload}, indent=2, ensure_ascii=False, default=str
                )
            )


def _gate(run: PipelineRun, phase: str) -> bool:
    gates, blocking = PHASE_GATES[phase]
    res = run_gates(run.state, gates)
    run.gates[phase] = res
    failed = [r for r in res if r.blocking and r.gate in blocking]
    if failed:
        run.status = "stopped"
        run.reason = f"{phase}: blocked by " + "; ".join(
            f"{r.gate} ({'; '.join(r.problems[:2])})" for r in failed
        )
        return False
    return True


def run_pipeline(
    case: SyntheticCase,
    lang: str = "de",
    llm_factory: Callable[[], LLMClient] | None = None,
    store: ClientStore | None = None,
    out_dir: str | Path | None = None,
    effects: list[OpportunityInput] | None = None,
    economics: Economics | None = None,
    sims: SimSettings | None = None,
) -> PipelineRun:
    s = State(engagement_id=case.id, title=case.title, lang=lang)
    run = PipelineRun(s)
    cp = Checkpoints(store)

    # ---- diagnose (phases 0-4) -----------------------------------------------------------
    base = run_case(case, lang=lang)
    s.goal, s.sources, s.metrics = case.goal, list(case.sources), list(case.metrics)
    s.graph, s.heat, s.report = case.graph(), base.heat, base.report
    s.phase = 4
    s.log.append(f"diagnose: binding={'none' if s.report.binding is None else s.report.binding.id}")
    proceed = _gate(run, "diagnose")
    if proceed and s.report.binding is None:
        run.status, run.reason = "stopped", "no confirmed constraint: discovery actions only (G4)"
        proceed = False
    if s.report.binding is not None and s.report.binding.domain_id in REGULATED_DOMAINS:
        run.human_review.append(
            f"regulated domain ({s.report.binding.domain_id}): human review of all outputs"
        )

    if proceed and llm_factory is not None:
        llm = llm_factory()
        b = s.report.binding
        pols = s.report.policy_audit.policies
        # ---- goal factoring (5) --------------------------------------------------------
        s.phase = 5
        key = cp.key(b.model_dump(mode="json"), lang, "goal_factoring/v1")
        cached = cp.load("goal_factoring", key)
        if cached:
            s.tree = GoalTree([GoalNode.model_validate(n) for n in cached["nodes"]])
            s.log.append("goal_factoring: resumed from checkpoint")
        else:
            from ..agents.goal_factoring import factor_goal

            try:
                s.tree = factor_goal(llm, b, s.graph, s.metrics, pols, lang=lang).result
            except AgentEscalation as exc:
                run.status, run.reason = "escalated", f"goal_factoring: {exc}"
                return _finish(run, out_dir)
            cp.save(
                "goal_factoring", key, {"nodes": [n.model_dump(mode="json") for n in s.tree.nodes]}
            )
        if not _gate(run, "goal_factoring"):
            return _finish(run, out_dir)
        # ---- opportunities (6) + critic --------------------------------------------------
        s.phase = 6
        seeds = s.tree.opportunity_seeds()
        if seeds:
            key = cp.key(key, [n.model_dump(mode="json") for n in seeds], "opportunity/v1")
            cached = cp.load("opportunities", key)
            if cached:
                from ..agents.opportunity_analyst import OpportunityAnalysis

                s.opportunities = OpportunityAnalysis(
                    [Opportunity.model_validate(o) for o in cached["opportunities"]],
                    [Risk.model_validate(r) for r in cached["risks"]],
                    cached["findings"],
                    cached["open_questions"],
                )
                s.log.append("opportunities: resumed from checkpoint")
            else:
                from ..agents.opportunity_analyst import analyse_opportunities

                for attempt in (1, 2):
                    try:
                        s.opportunities = analyse_opportunities(
                            llm, seeds, b, s.graph, pols, lang=lang
                        ).result
                    except AgentEscalation as exc:
                        run.status, run.reason = "escalated", f"opportunities: {exc}"
                        return _finish(run, out_dir)
                    blocks = [f for f in critique(s) if f.severity is FindingSeverity.blocking]
                    if not blocks:
                        break
                    if attempt == 2:
                        s.findings += blocks
                        run.status = "escalated"
                        run.reason = "critic blocked twice: " + "; ".join(
                            f.statement for f in blocks[:3]
                        )
                        return _finish(run, out_dir)
                o = s.opportunities
                cp.save(
                    "opportunities",
                    key,
                    {
                        "opportunities": [x.model_dump(mode="json") for x in o.opportunities],
                        "risks": [x.model_dump(mode="json") for x in o.risks],
                        "findings": o.findings,
                        "open_questions": o.open_questions,
                    },
                )
            low = [o.id for o in s.opportunities.opportunities if (o.confidence or 0) < 0.5]
            if low:
                run.human_review.append(f"confidence < 0.5 on {', '.join(low)}")
            if not _gate(run, "opportunities"):
                return _finish(run, out_dir)
            # ---- feasibility (7) -------------------------------------------------------
            s.phase = 7
            s.feasibility = [
                assess(o, by_id(o.pattern) if o.pattern else None, domain=b.domain_id)
                for o in s.opportunities.opportunities
            ]
            if any(f.status == "blocked" for f in s.feasibility):
                run.human_review.append(
                    "feasibility blocked for: "
                    + ", ".join(f.opportunity_id for f in s.feasibility if f.status == "blocked")
                )
            _gate(run, "feasibility")

    # ---- plan (8): value + roadmap ---------------------------------------------------------
    if s.report.binding is not None and run.status == "running":
        s.phase = 8
        if effects and economics and s.graph is not None:
            s.value = value_portfolio(s.graph, effects, economics, sims)
        s.roadmap = plan(s.report, s.tree, s.opportunities, s.graph, s.metrics, lang=lang)
        _gate(run, "plan")
    s.findings += [f for f in critique(s) if f.severity is not FindingSeverity.blocking]
    return _finish(run, out_dir, economics)


def _finish(run: PipelineRun, out_dir, economics: Economics | None = None) -> PipelineRun:
    s = run.state
    s.phase = 14
    run.gates["report"] = run_gates(s, PHASE_GATES["report"][0])
    if out_dir is not None and s.heat is not None and s.report is not None:
        decisions = list(run.human_review)
        if run.status in ("stopped", "escalated"):
            decisions.insert(0, run.reason)
        b = Bundle(
            s.title,
            s.lang,
            s.heat,
            s.report,
            s.graph,
            s.metrics,
            tree=s.tree,
            opportunities=s.opportunities,
            value=s.value,
            economics=economics,
            feasibility=s.feasibility,
            roadmap=s.roadmap,
            open_decisions=decisions,
            goal=s.goal,
        )
        run.report_paths = write(b, out_dir)
        from ..qa.gates import to_markdown as gates_md

        gp = Path(out_dir) / "10-quality-gates.md"
        gp.write_text(
            "\n\n".join(f"## {phase}\n\n{gates_md(res)}" for phase, res in run.gates.items()) + "\n"
        )
        run.report_paths.append(gp)
    if run.status == "running":
        run.status = "awaiting_review"
        run.reason = "deliverables drafted: human review required before client delivery (§16)"
    return run
