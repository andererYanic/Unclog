"""Flow graph market -> cash with offered-load propagation (brief §8.1-8.2).

Demand at each node is the solution of ``lambda = lambda0 + P^T lambda``, where ``lambda0`` are
external arrivals and ``P`` the routing probabilities. This handles funnels (RACE conversions as
edge probabilities), branches and rework loops in one linear solve. Probability not routed on
any edge leaves the system (lost leads, cancelled orders).

This is static, offered-load analysis: utilization > 1 means a resource cannot keep up. Dynamics
(queues building, variability, buffers) are the simulation engine's job (brief §10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..schemas.diagnosis import DomainName, FlowEdge, FlowNode, Resource
from .distributions import arrivals_per_week, cv, service_hours
from .units import hours_per_week

_EPS = 1e-9


class FlowGraphError(ValueError):
    pass


@dataclass(frozen=True)
class ResourceLoad:
    resource_id: str
    load_h: float  # work hours demanded per week
    capacity_h: float  # work hours available per week
    node_ids: tuple[str, ...]

    @property
    def utilization(self) -> float:
        return math.inf if self.capacity_h <= 0 else self.load_h / self.capacity_h


@dataclass(frozen=True)
class NodeLoad:
    node_id: str
    domain: str
    demand_per_week: float
    service_h: float | None
    service_cv: float | None
    utilization: float | None  # max utilization among the node's resources
    est_wait_h: float | None  # queueing approximation; inf if overloaded
    observed_wait_h: float | None
    touch_h: float | None
    queue_length: float | None

    @property
    def flow_efficiency(self) -> float | None:
        """touch / (touch + wait); usually low: elapsed time is mostly waiting (brief §8.1)."""
        wait = self.observed_wait_h
        if self.touch_h is None or wait is None or (self.touch_h + wait) == 0:
            return None
        return self.touch_h / (self.touch_h + wait)


@dataclass
class FlowGraph:
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    resources: list[Resource]
    tasks: list = field(default_factory=list)  # schemas.diagnosis.Task
    arrival_scale: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._idx = {n.id: i for i, n in enumerate(self.nodes)}
        if len(self._idx) != len(self.nodes):
            raise FlowGraphError("duplicate node ids")
        self._res = {r.id: r for r in self.resources}
        if len(self._res) != len(self.resources):
            raise FlowGraphError("duplicate resource ids")
        valid_domains = {d.value for d in DomainName}
        for n in self.nodes:
            if n.domain_id not in valid_domains:
                raise FlowGraphError(
                    f"node {n.id}: domain_id {n.domain_id!r} must be a DomainName value"
                )
            for r in n.resource_ids:
                if r not in self._res:
                    raise FlowGraphError(f"node {n.id}: unknown resource {r!r}")
        out: dict[str, float] = {}
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in self._idx:
                    raise FlowGraphError(f"edge {e.source}->{e.target}: unknown node {end!r}")
            out[e.source] = out.get(e.source, 0.0) + e.probability
        for nid, p in out.items():
            if p > 1 + 1e-6:
                raise FlowGraphError(f"node {nid}: outgoing probabilities sum to {p:.3f} > 1")
        for t in self.tasks:
            if t.node_id not in self._idx:
                raise FlowGraphError(f"task {t.id}: unknown node {t.node_id!r}")
            if t.resource_id and t.resource_id not in self._res:
                raise FlowGraphError(f"task {t.id}: unknown resource {t.resource_id!r}")
        if not any(n.arrival for n in self.nodes):
            raise FlowGraphError("no node has external arrivals; nothing enters the system")

    # ---- structure -------------------------------------------------------------------------
    def node(self, node_id: str) -> FlowNode:
        return self.nodes[self._idx[node_id]]

    def entries(self) -> list[str]:
        return [n.id for n in self.nodes if n.arrival is not None]

    def sinks(self) -> list[str]:
        sources = {e.source for e in self.edges}
        return [n.id for n in self.nodes if n.id not in sources]

    def reachable_from_entries(self) -> set[str]:
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            if e.probability > 0:
                adj.setdefault(e.source, []).append(e.target)
        seen, stack = set(), list(self.entries())
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                stack.extend(adj.get(n, []))
        return seen

    def has_cycle(self) -> bool:
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e.source, []).append(e.target)
        state: dict[str, int] = {}

        def visit(n: str) -> bool:
            state[n] = 1
            for m in adj.get(n, []):
                if state.get(m) == 1 or (state.get(m) is None and visit(m)):
                    return True
            state[n] = 2
            return False

        return any(state.get(n.id) is None and visit(n.id) for n in self.nodes)

    # ---- demand ----------------------------------------------------------------------------
    def with_arrival_scale(self, factor: float, entries: list[str] | None = None) -> FlowGraph:
        """What-if: scale external arrivals (e.g. +30% leads = 1.3) on some or all entries."""
        targets = entries or self.entries()
        scale = dict(self.arrival_scale)
        for e in targets:
            scale[e] = scale.get(e, 1.0) * factor
        return FlowGraph(self.nodes, self.edges, self.resources, self.tasks, scale)

    def with_capacity_scale(self, resource_id: str, factor: float) -> FlowGraph:
        """What-if: scale one resource's capacity (e.g. +10% relief test = 1.1)."""
        if resource_id not in self._res:
            raise FlowGraphError(f"unknown resource {resource_id!r}")
        resources = [
            r.model_copy(update={"count": r.count * factor}) if r.id == resource_id else r
            for r in self.resources
        ]
        return FlowGraph(self.nodes, self.edges, resources, self.tasks, dict(self.arrival_scale))

    def effective_throughput(self) -> float:
        """Completions/week the system can actually deliver: offered throughput, capped by the
        busiest resource. Exact for a single chain, an approximation for branching flows."""
        b = self.bottleneck()
        offered = self.throughput()
        if b is None or b.utilization <= 1:
            return offered
        return offered / b.utilization

    def drum_rate(self, resource_id: str) -> float:
        """Items per week passing through the resource's nodes, capped by its capacity."""
        rl = self.resource_loads()[resource_id]
        d = self.demand()
        return sum(d[n] for n in rl.node_ids) / max(1.0, rl.utilization)

    def downstream_nodes(self, node_ids: set[str]) -> set[str]:
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            if e.probability > 0:
                adj.setdefault(e.source, []).append(e.target)
        seen: set[str] = set()
        stack = [t for n in node_ids for t in adj.get(n, [])]
        while stack:
            n = stack.pop()
            if n not in seen and n not in node_ids:
                seen.add(n)
                stack.extend(adj.get(n, []))
        return seen

    def demand(self) -> dict[str, float]:
        n = len(self.nodes)
        lam0 = np.zeros(n)
        for node in self.nodes:
            if node.arrival is not None:
                lam0[self._idx[node.id]] = arrivals_per_week(node.arrival) * self.arrival_scale.get(
                    node.id, 1.0
                )
        P = np.zeros((n, n))
        for e in self.edges:
            P[self._idx[e.source], self._idx[e.target]] += e.probability
        A = np.eye(n) - P.T
        try:
            lam = np.linalg.solve(A, lam0)
        except np.linalg.LinAlgError as exc:
            raise FlowGraphError("routing has a closed loop with no exit (probability 1)") from exc
        if np.any(lam < -_EPS):
            raise FlowGraphError("negative demand; check routing probabilities")
        return {node.id: float(max(lam[self._idx[node.id]], 0.0)) for node in self.nodes}

    def throughput(self) -> float:
        """Offered completions per week at sink nodes (units of throughput, before capacity)."""
        d = self.demand()
        return sum(d[s] for s in self.sinks())

    # ---- load / capacity -------------------------------------------------------------------
    def resource_loads(self) -> dict[str, ResourceLoad]:
        """load = demand rate x service time (+ setup per batch); utilization = load / capacity.

        Tasks with a resource take precedence. A node without tasks splits its service time
        across its resources in proportion to their count (a pooled team).
        """
        d = self.demand()
        load = {r: 0.0 for r in self._res}
        nodes_of: dict[str, set[str]] = {r: set() for r in self._res}
        tasks_by_node: dict[str, list] = {}
        for t in self.tasks:
            tasks_by_node.setdefault(t.node_id, []).append(t)
        for node in self.nodes:
            lam = d[node.id]
            batch = node.batch_size or 1.0
            node_tasks = [t for t in tasks_by_node.get(node.id, []) if t.resource_id]
            if node_tasks:
                for t in node_tasks:
                    svc = service_hours(t.service) if t.service else 0.0
                    load[t.resource_id] += lam * svc + (lam / batch) * t.setup_time_h
                    nodes_of[t.resource_id].add(node.id)
            elif node.service is not None and node.resource_ids:
                svc = service_hours(node.service)
                total = sum(self._res[r].count for r in node.resource_ids)
                for r in node.resource_ids:
                    load[r] += lam * svc * self._res[r].count / total
                    nodes_of[r].add(node.id)
        return {
            rid: ResourceLoad(
                resource_id=rid,
                load_h=load[rid],
                capacity_h=hours_per_week(r.count * r.hours_per_period, r.period),
                node_ids=tuple(sorted(nodes_of[rid])),
            )
            for rid, r in self._res.items()
        }

    def node_loads(self) -> dict[str, NodeLoad]:
        d = self.demand()
        rl = self.resource_loads()
        out = {}
        for node in self.nodes:
            utils = [rl[r].utilization for r in node.resource_ids if r in rl]
            u = max(utils) if utils else None
            svc = service_hours(node.service) if node.service else None
            scv = cv(node.service) if node.service else None
            servers = sum(self._res[r].count for r in node.resource_ids) or None
            ca = cv(node.arrival) if node.arrival else 1.0  # internal flows: assume Poisson-like
            est = _sakasegawa_wait(u, servers, svc, ca, scv)
            observed = node.wait_time_h
            if observed is None and node.queue_length is not None and d[node.id] > 0:
                # Little's law: W = L / lambda (calendar hours)
                observed = node.queue_length / d[node.id] * 168.0
            out[node.id] = NodeLoad(
                node_id=node.id,
                domain=node.domain_id,
                demand_per_week=d[node.id],
                service_h=svc,
                service_cv=scv,
                utilization=u,
                est_wait_h=est,
                observed_wait_h=observed,
                touch_h=node.touch_time_h if node.touch_time_h is not None else svc,
                queue_length=node.queue_length,
            )
        return out

    def bottleneck(self) -> ResourceLoad | None:
        """Highest-utilization resource. A *candidate* only: confirmation is step 5 (G4)."""
        rl = [r for r in self.resource_loads().values() if r.load_h > 0]
        return max(rl, key=lambda r: r.utilization) if rl else None

    def demand_headroom(self) -> float:
        """Fractional demand growth until the first resource reaches 100% (negative = over)."""
        b = self.bottleneck()
        if b is None or b.utilization == 0:
            return math.inf
        return 1 / b.utilization - 1


def _sakasegawa_wait(
    rho: float | None, c: float | None, ts: float | None, ca: float, cs: float | None
) -> float | None:
    """G/G/c queue-wait approximation (work hours). Indicator only; simulation is authoritative."""
    if rho is None or c is None or ts is None or cs is None:
        return None
    if rho >= 1:
        return math.inf
    if rho <= 0:
        return 0.0
    c = max(c, 1.0)
    return (rho ** (math.sqrt(2 * (c + 1)) - 1) / (c * (1 - rho))) * ((ca**2 + cs**2) / 2) * ts
