import pytest
from pydantic import ValidationError

from unclog.schemas import DeltaOE, GoalNode, Opportunity, RealizationPath


def test_goal_tree_shape(ev):
    GoalNode(
        id="g0",
        kind="root",
        statement="Approvals/day 61->84",
        metric="approvals/day",
        evidence=[ev()],
    )
    with pytest.raises(ValidationError, match="measurable"):
        GoalNode(id="g0", kind="root", statement="be better", evidence=[ev()])
    with pytest.raises(ValidationError, match="parent"):
        GoalNode(id="g1", kind="option", statement="x", evidence=[ev()])
    with pytest.raises(ValidationError, match="tag"):
        GoalNode(id="g2", parent_id="g1", kind="base_action", statement="x", evidence=[ev()])


def test_mirage_detection():
    oe = DeltaOE(amount=-4000, capacity_released_h=120)
    assert oe.is_mirage and oe.realized_amount == 0.0
    path = RealizationPath(kind="contractor_reduction", owner="COO", timing="Q1", probability=0.7)
    oe2 = DeltaOE(amount=-4000, realization_path=path)
    assert not oe2.is_mirage and oe2.realized_amount == -4000
    with pytest.raises(ValidationError, match="target_role"):
        RealizationPath(kind="redeployment_to_constraint", owner="x", timing="t", probability=0.5)


def _opp(ev, **kw):
    base = dict(
        id="o1",
        title="Pre-fill refund tickets",
        ai_role="assist",
        position="at_constraint",
        focus_step="exploit",
        constraint_id="c1",
        constraint_link="acts_on",
        proven=True,
        proof_refs=["lib:ticket-prefill"],
        process_health_ok=True,
        evidence=[ev()],
    )
    return Opportunity(**{**base, **kw})


def test_valid_opportunity(ev):
    assert _opp(ev, priority="exploit-now").priority == "exploit-now"


def test_unproven_must_be_rd(ev):
    with pytest.raises(ValidationError, match="rd_label"):
        _opp(ev, proven=False, proof_refs=[])
    assert _opp(ev, proven=False, proof_refs=[], rd_label=True).rd_label


def test_broken_process_must_fix_first(ev):
    with pytest.raises(ValidationError, match="fix-process-first"):
        _opp(ev, process_health_ok=False, priority="exploit-now")
    _opp(ev, process_health_ok=False, priority="fix-process-first")


def test_upstream_requires_release_gate(ev):
    with pytest.raises(ValidationError, match="release gate"):
        _opp(ev, position="upstream")
    with pytest.raises(ValidationError, match="not designed"):
        _opp(ev, position="upstream", release_gate_required=True, priority="subordinate")
    _opp(
        ev,
        position="upstream",
        release_gate_required=True,
        priority="subordinate",
        release_gate_design="WIP limit 40 tickets ahead of Tier-2",
    )


def test_ncx10_off_constraint_defaults_to_defer(ev):
    with pytest.raises(ValidationError, match="defer"):
        _opp(ev, constraint_link="off_constraint", position="off_flow", priority="exploit-now")
    _opp(ev, constraint_link="off_constraint", position="off_flow", priority="defer")
