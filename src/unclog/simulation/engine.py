"""Discrete-event simulation of a FlowGraph (brief §10).

Model:
- Time is calendar hours. Entities arrive at entry nodes and route along edge probabilities;
  probability not routed leaves the system (lost), sinks count as completions.
- A node with resources queues FIFO for a server pool. A resource with ``count`` people working
  ``hours_per_period`` is modelled as ``round(count)`` servers whose service times are stretched
  by their availability (``168 / work hours per week``). Simulated utilization therefore matches
  the static load/capacity ratio, while queues and waits come from variability and dependency.
  Nodes with several resources use one pooled server group; a resource used alone at one node and
  pooled at another gets independent capacity there (approximation; flagged in decision 006).
- A node with ``batch_size > 1`` holds items until a full batch is collected, then releases them
  together (a batching policy).
- Tasks on a node add their service times (plus setup per batch) to the node's service.
- An optional **rope** gate at a node caps WIP from that node onward; arrivals over the cap wait
  in a release backlog outside the system (Drum-Buffer-Rope, brief §2.3).
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ..flow.graph import FlowGraph
from ..flow.units import hours_per_week
from .sampling import interarrival_hours, service_hours

ARRIVE, DONE, BATCH_SETUP_DONE, RENEGE = 0, 1, 2, 3


@dataclass
class _Pool:
    key: str
    servers: int
    availability: float  # fraction of calendar time each server works
    busy: int = 0
    queue: deque = field(default_factory=deque)
    busy_area: float = 0.0
    last: float = 0.0

    def touch(self, t: float) -> None:
        self.busy_area += self.busy * (t - self.last)
        self.last = t


@dataclass
class RepResult:
    throughput_per_week: float
    lead_times_h: list[float]  # customer view: arrival to completion (incl. release backlog)
    internal_lead_times_h: list[float]  # shop view: release to completion
    wip_by_node: dict[str, float]
    queue_by_node: dict[str, float]
    utilization: dict[str, float]
    max_queue_by_node: dict[str, int]
    completed: int
    lost: int
    reneged: int  # left a queue because they waited longer than the node's patience
    gate_backlog_end: int
    gate_wait_h: list[float]

    @property
    def constraint_location(self) -> str | None:
        return max(self.utilization, key=self.utilization.get) if self.utilization else None


class Simulator:
    def __init__(
        self,
        graph: FlowGraph,
        seed: int = 0,
        rope: tuple[str, int] | None = None,
        batch_override: dict[str, float] | None = None,
    ) -> None:
        self.g = graph
        self.rng = np.random.default_rng(seed)
        self.rope = rope
        self.batch = {
            n.id: int(round((batch_override or {}).get(n.id, n.batch_size or 1)))
            for n in graph.nodes
        }
        self.routes: dict[str, list[tuple[str, float]]] = {}
        for e in graph.edges:
            self.routes.setdefault(e.source, []).append((e.target, e.probability))
        self.sinks = set(graph.sinks())
        res = {r.id: r for r in graph.resources}
        self.pool_of: dict[str, _Pool] = {}
        pools: dict[str, _Pool] = {}
        for n in graph.nodes:
            if not n.resource_ids:
                continue
            key = "+".join(sorted(n.resource_ids))
            if key not in pools:
                people = sum(res[r].count for r in n.resource_ids)
                hours = sum(
                    hours_per_week(res[r].count * res[r].hours_per_period, res[r].period)
                    for r in n.resource_ids
                )
                servers = max(1, int(round(people)))
                pools[key] = _Pool(key, servers, min(1.0, hours / (servers * 168.0)))
            self.pool_of[n.id] = pools[key]
        self.pools = pools
        self.tasks: dict[str, list] = {}
        for t in graph.tasks:
            self.tasks.setdefault(t.node_id, []).append(t)
        self.gate_after: set[str] = set()
        if rope:
            self.gate_after = {rope[0], *graph.downstream_nodes({rope[0]})}

    # ---- helpers ----------------------------------------------------------------------------
    def _service_calendar_h(self, node_id: str, pool: _Pool | None) -> float:
        node = self.g.node(node_id)
        work = 0.0
        if node_id in self.tasks:
            for t in self.tasks[node_id]:
                if t.service is not None:
                    work += service_hours(t.service, self.rng)
                work += t.setup_time_h / max(1, self.batch[node_id])
        elif node.service is not None:
            work = service_hours(node.service, self.rng)
        if pool is None:
            return work  # pure delay
        return work / pool.availability

    def _next(self, node_id: str) -> str | None:
        options = self.routes.get(node_id)
        if not options:
            return None
        u = self.rng.random()
        acc = 0.0
        for target, p in options:
            acc += p
            if u < acc:
                return target
        return "__lost__"

    # ---- run --------------------------------------------------------------------------------
    def run(self, horizon_weeks: float = 26, warmup_weeks: float = 4) -> RepResult:
        T = horizon_weeks * 168.0
        W = warmup_weeks * 168.0
        heap: list = []
        seq = itertools.count()
        scale = self.g.arrival_scale

        def push(t, kind, payload):
            heapq.heappush(heap, (t, next(seq), kind, payload))

        for n in self.g.nodes:
            if n.arrival is not None:
                push(
                    interarrival_hours(n.arrival, self.rng, scale.get(n.id, 1.0)),
                    ARRIVE,
                    ("ext", n.id),
                )

        born: dict[int, float] = {}
        ids = itertools.count()
        in_node: dict[str, int] = {n.id: 0 for n in self.g.nodes}
        in_queue: dict[str, int] = {n.id: 0 for n in self.g.nodes}
        node_area = dict.fromkeys(in_node, 0.0)
        queue_area = dict.fromkeys(in_node, 0.0)
        max_q = dict.fromkeys(in_node, 0)
        last = [0.0]
        batch_buf: dict[str, list[int]] = {n.id: [] for n in self.g.nodes}
        gate_wip = [0]
        gate_backlog: deque = deque()
        gate_enter: dict[int, float] = {}
        gate_waits: list[float] = []
        lead: list[float] = []
        internal: list[float] = []  # from release (gate entry, else arrival) to completion
        completed = lost = 0
        waiting: set[tuple[int, str]] = set()  # (entity, node) in a queue with patience
        reneged = [0]

        def account(t):
            dt = t - last[0]
            if dt > 0 and t > W:
                eff = t - max(last[0], W)
                for k in in_node:
                    node_area[k] += in_node[k] * eff
                    queue_area[k] += in_queue[k] * eff
            last[0] = t

        def leave_system(eid, t, done):
            nonlocal completed, lost
            b = born.pop(eid)
            released = gate_enter.pop(eid, None)
            if released is not None:
                gate_wip[0] -= 1
                release_from_gate(t)
            if done:
                if b >= W and t <= T:
                    lead.append(t - b)
                    internal.append(t - (released if released is not None else b))
                if t >= W:
                    completed += 1
            elif t >= W:
                lost += 1

        def release_from_gate(t):
            while gate_backlog and gate_wip[0] < self.rope[1]:
                eid, t_arr = gate_backlog.popleft()
                if t_arr >= W:
                    gate_waits.append(t - t_arr)
                gate_wip[0] += 1
                gate_enter[eid] = t
                enter(eid, self.rope[0], t, through_gate=True)

        def start_service(eid, node_id, t):
            pool = self.pool_of.get(node_id)
            if pool is not None:
                pool.touch(t)
                pool.busy += 1
            push(t + self._service_calendar_h(node_id, pool), DONE, (eid, node_id))

        def enter(eid, node_id, t, through_gate=False):
            if self.rope and node_id == self.rope[0] and not through_gate and eid not in gate_enter:
                if gate_wip[0] >= self.rope[1]:
                    gate_backlog.append((eid, t))
                    return
                gate_wip[0] += 1
                gate_enter[eid] = t
            node = self.g.node(node_id)
            if node.service is None and node_id not in self.tasks:
                route(eid, node_id, t)
                return
            in_node[node_id] += 1
            b = self.batch[node_id]
            if b > 1:
                batch_buf[node_id].append(eid)
                in_queue[node_id] += 1
                if len(batch_buf[node_id]) < b:
                    max_q[node_id] = max(max_q[node_id], in_queue[node_id])
                    return
                released, batch_buf[node_id] = batch_buf[node_id], []
                in_queue[node_id] -= len(released)
            else:
                released = [eid]
            pool = self.pool_of.get(node_id)
            for e in released:
                if pool is None:
                    start_service(e, node_id, t)
                elif pool.busy < pool.servers:
                    start_service(e, node_id, t)
                else:
                    pool.queue.append((e, node_id))
                    in_queue[node_id] += 1
                    max_q[node_id] = max(max_q[node_id], in_queue[node_id])
                    if node.patience_h:
                        waiting.add((e, node_id))
                        push(t + node.patience_h, RENEGE, (e, node_id))

        def route(eid, node_id, t):
            nxt = self._next(node_id)
            if nxt is None:
                leave_system(eid, t, done=True)
            elif nxt == "__lost__":
                leave_system(eid, t, done=False)
            else:
                enter(eid, nxt, t)

        while heap:
            t, _, kind, payload = heapq.heappop(heap)
            if t > T:
                break
            account(t)
            if kind == ARRIVE:
                _, node_id = payload
                node = self.g.node(node_id)
                push(
                    t + interarrival_hours(node.arrival, self.rng, scale.get(node_id, 1.0)),
                    ARRIVE,
                    ("ext", node_id),
                )
                eid = next(ids)
                born[eid] = t
                enter(eid, node_id, t)
            elif kind == DONE:
                eid, node_id = payload
                in_node[node_id] -= 1
                pool = self.pool_of.get(node_id)
                if pool is not None:
                    pool.touch(t)
                    pool.busy -= 1
                    if pool.queue:
                        e2, n2 = pool.queue.popleft()
                        waiting.discard((e2, n2))
                        in_queue[n2] -= 1
                        start_service(e2, n2, t)
                route(eid, node_id, t)
            elif kind == RENEGE:
                eid, node_id = payload
                if (eid, node_id) in waiting:  # still waiting: the customer gives up
                    waiting.discard((eid, node_id))
                    self.pool_of[node_id].queue.remove((eid, node_id))
                    in_queue[node_id] -= 1
                    in_node[node_id] -= 1
                    if t >= W:
                        reneged[0] += 1
                    leave_system(eid, t, done=False)

        account(T)
        span = max(T - W, 1e-9)
        for p in self.pools.values():
            p.touch(T)
        # Busy server-time over available server-time (calendar). Service times are stretched by
        # availability, so this equals load / capacity in the static model's terms.
        util = {p.key: p.busy_area / (p.servers * T) for p in self.pools.values()}
        return RepResult(
            throughput_per_week=completed / (span / 168.0),
            lead_times_h=lead,
            internal_lead_times_h=internal,
            wip_by_node={k: v / span for k, v in node_area.items()},
            queue_by_node={k: v / span for k, v in queue_area.items()},
            utilization=util,
            max_queue_by_node=max_q,
            completed=completed,
            lost=lost,
            reneged=reneged[0],
            gate_backlog_end=len(gate_backlog),
            gate_wait_h=gate_waits,
        )


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values), q * 100))


def finite(x: float | None) -> float | None:
    return None if x is None or math.isinf(x) or math.isnan(x) else x
