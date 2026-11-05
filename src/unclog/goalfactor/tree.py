"""Goal tree: validation, TOC pruning, ranking, rendering (brief §7).

Rules enforced here (deterministic):
- one root, every parent exists, no cycles -> every leaf traces to the root
- base actions sit at depth >= 2, carry a tag and a constraint link, and are doable in days
- the tree contains at least one non-AI fix (brief §3: "no AI" is a valid answer)
- exploit-step actions exist (brief §8.7: exploit before elevate)
- pruning: base actions that don't act on, protect or gate flow to the constraint are pruned
  (value zero until a realization path exists); options left with no live action are pruned
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.design import ActionTag, ConstraintLink, GoalNode, GoalNodeKind, GoalNodeStatus
from ..schemas.diagnosis import FocusStep

MAX_EFFORT_DAYS = 10.0
MIN_LIVE_ACTIONS = 3

_STEP_ORDER = {FocusStep.exploit: 0, FocusStep.subordinate: 1, FocusStep.elevate: 2}
_LINK_ORDER = {ConstraintLink.acts_on: 0, ConstraintLink.protects: 1, ConstraintLink.gates_flow: 2}


@dataclass
class GoalTree:
    nodes: list[GoalNode]

    def __post_init__(self) -> None:
        self._by_id = {n.id: n for n in self.nodes}

    # ---- structure -------------------------------------------------------------------------
    @property
    def root(self) -> GoalNode:
        return next(n for n in self.nodes if n.kind is GoalNodeKind.root)

    def node(self, node_id: str) -> GoalNode:
        return self._by_id[node_id]

    def children(self, node_id: str) -> list[GoalNode]:
        return [n for n in self.nodes if n.parent_id == node_id]

    def path(self, node_id: str) -> list[GoalNode]:
        out, seen = [], set()
        cur = self._by_id.get(node_id)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            out.append(cur)
            cur = self._by_id.get(cur.parent_id) if cur.parent_id else None
        return list(reversed(out))

    def depth(self, node_id: str) -> int:
        return len(self.path(node_id)) - 1

    def base_actions(self, live_only: bool = False) -> list[GoalNode]:
        return [
            n
            for n in self.nodes
            if n.kind is GoalNodeKind.base_action
            and (not live_only or n.status is not GoalNodeStatus.pruned)
        ]

    # ---- validation ------------------------------------------------------------------------
    def structure_problems(self) -> list[str]:
        problems = []
        roots = [n for n in self.nodes if n.kind is GoalNodeKind.root]
        if len(roots) != 1:
            problems.append(f"exactly one root required, found {len(roots)}")
        if len(self._by_id) != len(self.nodes):
            problems.append("duplicate node ids")
        for n in self.nodes:
            if n.parent_id and n.parent_id not in self._by_id:
                problems.append(f"{n.id}: parent {n.parent_id!r} does not exist")
            elif (
                n.kind is not GoalNodeKind.root and self.path(n.id)[0].kind is not GoalNodeKind.root
            ):
                problems.append(f"{n.id}: does not trace to the root (cycle?)")
        return problems

    def quality_problems(self, require_policy_branch: str | None = None) -> list[str]:
        """Checks on a pruned tree. ``require_policy_branch``: option id that must keep a live
        base action (policy constraints: challenge the rule before automating it)."""
        problems = []
        # Pruned off-constraint items are kept only to explain "why not"; check live ones.
        for a in self.base_actions(live_only=True):
            if self.depth(a.id) < 2:
                problems.append(f"{a.id}: base action must sit under an option (depth >= 2)")
            if a.effort_days is None or a.effort_days > MAX_EFFORT_DAYS:
                problems.append(
                    f"{a.id}: base actions must be doable in days "
                    f"(effort_days <= {MAX_EFFORT_DAYS:g}); split it"
                )
            if a.focus_step is None:
                problems.append(f"{a.id}: focus_step missing")
        live = self.base_actions(live_only=True)
        if len(live) < MIN_LIVE_ACTIONS:
            problems.append(
                f"only {len(live)} live base actions after pruning; need >= "
                f"{MIN_LIVE_ACTIONS} that act on, protect or gate the constraint"
            )
        if not any(a.tag is ActionTag.non_ai for a in live):
            problems.append(
                "no non-AI fix among live actions (process or policy change); add "
                "at least one: often the cheapest exploit needs no AI"
            )
        if not any(a.focus_step is FocusStep.exploit for a in live):
            problems.append("no exploit-step action: exploit the constraint before elevating")
        if require_policy_branch:
            branch = [
                a for a in live if any(p.id == require_policy_branch for p in self.path(a.id))
            ]
            if not branch:
                problems.append(
                    f"policy branch {require_policy_branch} has no live action: "
                    "challenge the rule before automating around it"
                )
        return problems

    # ---- TOC pruning and ranking -----------------------------------------------------------
    def prune(self) -> GoalTree:
        nodes = []
        for n in self.nodes:
            if (
                n.kind is GoalNodeKind.base_action
                and n.constraint_link is ConstraintLink.off_constraint
            ):
                n = n.model_copy(update={"status": GoalNodeStatus.pruned})
            nodes.append(n)
        tree = GoalTree(nodes)
        live_ids = {a.id for a in tree.base_actions(live_only=True)}
        keep = {p.id for a in live_ids for p in tree.path(a)}
        out = []
        for n in tree.nodes:
            if n.kind is GoalNodeKind.option and n.id not in keep:
                n = n.model_copy(update={"status": GoalNodeStatus.pruned})
            elif (
                n.kind is GoalNodeKind.base_action
                and n.id in live_ids
                or n.kind is GoalNodeKind.option
                and n.id in keep
            ):
                n = n.model_copy(update={"status": GoalNodeStatus.chosen})
            out.append(n)
        return GoalTree(out)

    def ranked_actions(self) -> list[GoalNode]:
        return sorted(
            self.base_actions(live_only=True),
            key=lambda a: (
                _STEP_ORDER.get(a.focus_step, 3),
                _LINK_ORDER.get(a.constraint_link, 3),
                a.effort_days or MAX_EFFORT_DAYS,
                a.id,
            ),
        )

    def opportunity_seeds(self) -> list[GoalNode]:
        """AI-doable / AI-assisted live actions: inputs to the Opportunity Analyst (step 9)."""
        return [
            a
            for a in self.ranked_actions()
            if a.tag in (ActionTag.ai_doable, ActionTag.ai_assisted)
        ]

    # ---- rendering -------------------------------------------------------------------------
    def to_markdown(self, lang: str = "en") -> str:
        L = {
            "en": ("Goal tree", "Ranked actions", "pruned", "days"),
            "de": ("Zielbaum", "Priorisierte Maßnahmen", "verworfen", "Tage"),
        }[lang]
        out = [f"## {L[0]}", ""]

        def walk(n: GoalNode, level: int) -> None:
            mark = f" ~~({L[2]})~~" if n.status is GoalNodeStatus.pruned else ""
            extra = []
            if n.kind is GoalNodeKind.base_action:
                extra = [
                    n.tag.value if n.tag else "",
                    n.focus_step.value if n.focus_step else "",
                    f"{n.effort_days:g} {L[3]}" if n.effort_days else "",
                ]
            meta = f" `{' · '.join(x for x in extra if x)}`" if extra else ""
            metric = f" — _{n.metric}_" if n.metric else ""
            out.append(f"{'  ' * level}- {n.statement}{metric}{meta}{mark}")
            for c in self.children(n.id):
                walk(c, level + 1)

        walk(self.root, 0)
        out += ["", f"## {L[1]}", ""]
        for i, a in enumerate(self.ranked_actions(), 1):
            owner = f" — {a.owner}" if a.owner else ""
            out.append(
                f"{i}. [{a.tag.value}] {a.statement} ({a.focus_step.value}, "
                f"{a.effort_days:g} {L[3]}){owner}"
            )
        return "\n".join(out)

    def to_mermaid(self) -> str:
        lines = ["graph TD"]
        for n in self.nodes:
            label = n.statement.replace('"', "'")[:70]
            shape = (
                f'(["{label}"])'
                if n.kind is GoalNodeKind.root
                else f'["{label}"]'
                if n.kind is GoalNodeKind.option
                else f'("{label}")'
            )
            lines.append(f"  {n.id.replace('-', '_')}{shape}")
            if n.parent_id:
                lines.append(f"  {n.parent_id.replace('-', '_')} --> {n.id.replace('-', '_')}")
            if n.status is GoalNodeStatus.pruned:
                lines.append(f"  style {n.id.replace('-', '_')} stroke-dasharray: 5 5")
        return "\n".join(lines)
