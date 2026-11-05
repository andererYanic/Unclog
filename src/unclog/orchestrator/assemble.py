"""Assemble a real client's material into a case the pipeline can run (decisions 003, 007).

Inputs, all from the client store:
- ingested sources (exports, event logs, transcripts, documents), used through their scrubbed
  store copies, so encrypted raw files are never decrypted to disk
- stage metrics extracted from calls (``extract-call``)
- the company goal and unit of throughput from call extractions (``reviews/*-extraction.json``)
- flow fragments in ``clients/<id>/flow/*.json``: measured fragments saved by
  ``flow-from-log --save`` plus any manual fragment the consultant writes (for example
  resources and service times). Later fragments override fields of nodes with the same id.

The output ``clients/<id>/case/case.json`` is a normal case: ``unclog pipeline --case`` runs it.
Everything missing is reported, never invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..evals.cases import SyntheticCase
from ..flow.graph import FlowGraphError
from ..schemas.common import Evidence, EvidenceType
from ..schemas.diagnosis import FlowEdge, FlowNode, Resource, StageMetric
from ..schemas.engagement import TIOE, Goal
from ..store import ClientStore


@dataclass
class AssembleReport:
    case_path: Path
    case: SyntheticCase
    gaps: list[str] = field(default_factory=list)


def flow_dir(store: ClientStore) -> Path:
    d = Path(store.root) / "flow"
    d.mkdir(exist_ok=True)
    return d


def save_fragment(
    store: ClientStore,
    name: str,
    nodes: list[FlowNode],
    edges: list[FlowEdge],
    domain: str | None = None,
    source_id: str | None = None,
    activity_nodes: dict[str, str] | None = None,
    resources: list[Resource] = (),
    actor: str = "flow_modeler",
    measured_rates: dict[str, float] | None = None,
) -> Path:
    path = flow_dir(store) / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "domain": domain,
                "source_id": source_id,
                "activity_nodes": activity_nodes or {},
                "nodes": [n.model_dump(mode="json", exclude_none=True) for n in nodes],
                "edges": [e.model_dump(mode="json") for e in edges],
                "resources": [r.model_dump(mode="json") for r in resources],
                "measured_rates": measured_rates or {},
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    store._audit("flow_fragment_saved", actor, fragment=name, nodes=len(nodes))
    return path


def calibration_gaps(case: SyntheticCase, rates: dict[str, float]) -> list[str]:
    """A step with a persistent queue runs at its capacity, so its measured completions per week
    reveal the real capacity. Warn when the model assumes clearly more."""
    if not rates or not case.nodes:
        return []
    g = case.graph()
    loads = g.resource_loads()
    gaps = []
    for n in g.nodes:
        rate = rates.get(n.id)
        if rate is None or not n.resource_ids or not (n.queue_length or 0) > 0:
            continue
        cap = min(loads[r].capacity_h for r in n.resource_ids)
        from ..flow.distributions import service_hours

        svc = service_hours(n.service) if n.service else None
        if not svc:
            continue
        modeled = cap / svc
        if modeled > rate * 1.1:
            gaps.append(
                f"capacity at '{n.name}' looks overestimated: the model allows "
                f"{modeled:.1f}/week, the data shows {rate:.1f}/week while work queues; "
                "calibrate hours or service time"
            )
    return gaps


def _merge(fragments: list[dict]) -> tuple[list[dict], list[dict], list[dict], dict, dict]:
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}
    resources: dict[str, dict] = {}
    activity: dict[str, str] = {}
    log_domains: dict[str, str] = {}
    for f in fragments:
        for n in f.get("nodes", []):
            nodes[n["id"]] = {
                **nodes.get(n["id"], {}),
                **{k: v for k, v in n.items() if v not in (None, [], {})},
            }
        for e in f.get("edges", []):
            edges[(e["source"], e["target"])] = e
        for r in f.get("resources", []):
            resources[r["id"]] = r
        activity.update(f.get("activity_nodes", {}))
        if f.get("source_id") and f.get("domain"):
            log_domains[f["source_id"]] = f["domain"]
    return (
        list(nodes.values()),
        list(edges.values()),
        list(resources.values()),
        activity,
        log_domains,
    )


def _goal(store: ClientStore) -> tuple[Goal | None, list[str]]:
    gaps = []
    reviews = Path(store.root) / "reviews"
    for p in sorted(reviews.glob("*-extraction.json")) if reviews.exists() else []:
        x = json.loads(p.read_text())
        if x.get("goal_statement") and x.get("unit_of_throughput"):
            src = p.name.removesuffix("-extraction.json")
            todo = "to confirm with the client"
            return Goal(
                statement=x["goal_statement"],
                unit_of_throughput=x["unit_of_throughput"],
                t_definition=todo,
                i_definition=todo,
                oe_definition=todo,
                baseline=TIOE(),
                horizon="12 months",
                evidence=[
                    Evidence(
                        id=f"ev-goal-{src}",
                        source_id=src,
                        type=EvidenceType.interview_claim,
                        locator="call",
                    )
                ],
            ), gaps
    gaps.append(
        "no goal and unit of throughput found in call extractions (G3): ask the "
        "goal questions or add it to the case by hand"
    )
    return None, gaps


def assemble(
    store: ClientStore, title: str, kind: str = "mixed", actor: str = "orchestrator"
) -> AssembleReport:
    gaps: list[str] = []
    source_ids = store.list_sources()
    ingested = {sid: store.get_source(sid, actor=actor) for sid in source_ids}
    sources = [r.source for r in ingested.values()]
    metrics = store.list(StageMetric)
    goal, g = _goal(store)
    gaps += g
    fragments = [json.loads(p.read_text()) for p in sorted(flow_dir(store).glob("*.json"))]
    nodes, edges, resources, activity, log_domains = _merge(fragments)
    for sid, r in ingested.items():
        if r.event_logs and sid not in log_domains:
            gaps.append(
                f"event log {sid} ({r.source.title}) has no flow fragment/domain: run "
                "`unclog flow-from-log ... --save` for it"
            )
    if not nodes:
        gaps.append("no flow model yet: demand vs capacity cannot be checked (G5)")
    elif not resources:
        gaps.append(
            "flow has no resources: add who does the work and service times in a "
            "manual fragment (clients/<id>/flow/manual.json) to compute load"
        )
    if not metrics:
        gaps.append("no stage metrics yet: run `unclog extract-call` on call transcripts")
    case = SyntheticCase.model_validate(
        {
            "id": store.client_id,
            "title": title,
            "kind": kind,
            "description": f"Assembled from {len(sources)} sources, {len(metrics)} metrics and "
            f"{len(fragments)} flow fragment(s).",
            "goal": goal.model_dump(mode="json") if goal else None,
            "sources": [s.model_dump(mode="json") for s in sources],
            "metrics": [m.model_dump(mode="json") for m in metrics],
            "nodes": nodes,
            "edges": edges,
            "resources": resources,
            "store_sources": [
                sid for sid in source_ids if sid not in log_domains and not ingested[sid].event_logs
            ]
            + list(log_domains),
            "event_log_domains": log_domains,
            "activity_nodes": activity,
        }
    )
    if case.nodes:
        try:
            case.graph()
            rates = {k: v for f in fragments for k, v in f.get("measured_rates", {}).items()}
            gaps += calibration_gaps(case, rates)
        except FlowGraphError as exc:
            gaps.append(f"flow model is invalid: {exc}")
    out = Path(store.root) / "case"
    out.mkdir(exist_ok=True)
    path = out / "case.json"
    path.write_text(case.model_dump_json(indent=2, exclude={"folder"}))
    store._audit("case_assembled", actor, gaps=len(gaps), sources=len(sources))
    return AssembleReport(path, case, gaps)
