from datetime import date, datetime

import pytest
from pydantic import ValidationError

from unclog.schemas import DeployedSystem, EvalCase, EvalRun, EvalSuite, SyncSession


def _sys(**kw):
    base = dict(
        id="s1",
        opportunity_id="o1",
        environment="client-cloud",
        client_owner="Ops lead",
        runbook_ref="runbooks/s1.md",
        rollback="disable routine",
        version="1.0.0",
        external_effect=True,
    )
    return DeployedSystem(**{**base, **kw})


def test_external_effect_safe_by_default():
    assert _sys().draft_safe
    with pytest.raises(ValidationError, match="approval"):
        _sys(draft_safe=False)
    _sys(draft_safe=False, go_live_approval_ref="approvals/2026-11-05-s1")


def test_eval_stats_are_deterministic_and_gate():
    suite = EvalSuite(
        id="e1",
        system_id="s1",
        rubric="r",
        pass_mean=7,
        pass_worst_case=5,
        cases=[EvalCase(id="k1", input_ref="cases/k1.json")],
    )
    run = EvalRun(
        id="r1",
        suite_id="e1",
        model="m",
        harness_version="h1",
        scores=[8, 8, 7, 9, 8, 7, 8, 9, 8, 6],
        timestamp=datetime(2026, 11, 5),
    )
    assert run.n == 10 and run.mean == pytest.approx(7.8) and run.worst_case == 6
    assert run.passes(suite)
    short = run.model_copy(update={"scores": [9, 9, 9]})
    assert not short.passes(suite)  # fewer than 10 runs per case
    floor = run.model_copy(update={"scores": [9] * 9 + [2]})
    assert not floor.passes(suite)  # worst-case floor violated
    with pytest.raises(ValidationError):
        EvalSuite(
            id="e2",
            system_id="s1",
            rubric="r",
            pass_mean=7,
            pass_worst_case=5,
            cases=[EvalCase(id="k", input_ref="x")],
            min_runs_per_case=3,
        )


def test_sync_session_privacy_gate():
    with pytest.raises(ValidationError, match="consent"):
        SyncSession(id="ss1", pod="sales", date=date(2026, 11, 5), used_log_mining=True)
    SyncSession(
        id="ss1",
        pod="sales",
        date=date(2026, 11, 5),
        used_log_mining=True,
        consent_ref="consent/works-council-2026-10",
    )
