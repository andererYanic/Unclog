import pytest
from pydantic import ValidationError

from unclog.schemas import (
    REQUIRED_DOMAINS,
    ConfirmationTest,
    Constraint,
    Domain,
    DomainName,
    EvidenceType,
    StageMetric,
)


def _metric(**kw):
    base = dict(
        id="m1",
        domain_id="d1",
        name="first response",
        value=72,
        unit="h",
        period="2026-10",
        measured=True,
        source_id="src1",
    )
    return StageMetric(**{**base, **kw})


def test_measured_metric_needs_source():
    with pytest.raises(ValidationError, match="source_id"):
        _metric(source_id=None)
    assert _metric(measured=False, source_id=None).measured is False


def test_domain_clear_needs_evidence():
    with pytest.raises(ValidationError, match="clear"):
        Domain(id="d1", name="finance", prior=0.1, verdict="clear")
    Domain(id="d1", name="finance", prior=0.1, verdict="clear", metrics=[_metric()])
    Domain(id="d2", name="hr", prior=0.1)  # not_assessed is allowed bare


def test_required_domains_cover_race_and_backend():
    assert {d for d in REQUIRED_DOMAINS if d.is_race} == {
        DomainName.race_r,
        DomainName.race_a,
        DomainName.race_c,
        DomainName.race_e,
    }
    assert DomainName.fulfillment in REQUIRED_DOMAINS
    assert DomainName.other not in REQUIRED_DOMAINS


def _constraint(ev, **kw):
    base = dict(
        id="c1",
        type="physical",
        domain_id="d-support",
        resource_id="tier2",
        description="Tier-2 refund approvers",
        evidence=[ev()],
    )
    return Constraint(**{**base, **kw})


def test_physical_constraint_needs_resource(ev):
    with pytest.raises(ValidationError, match="resource_id"):
        _constraint(ev, resource_id=None)
    with pytest.raises(ValidationError, match="policy_id"):
        _constraint(ev, type="policy", resource_id=None)


def test_confirmed_needs_two_independent_evidence_types(ev):
    passed = [ConfirmationTest(kind="queue", passed=True)]
    with pytest.raises(ValidationError, match="independent"):
        _constraint(
            ev,
            status="confirmed",
            tests_run=passed,
            demand_vs_capacity_checked=True,
            evidence=[ev(EvidenceType.log_data, 1), ev(EvidenceType.log_data, 2)],
        )
    with pytest.raises(ValidationError, match="passed test"):
        _constraint(
            ev,
            status="confirmed",
            demand_vs_capacity_checked=True,
            evidence=[ev(EvidenceType.log_data, 1), ev(EvidenceType.interview_claim, 2)],
        )
    with pytest.raises(ValidationError, match="both-direction"):
        _constraint(
            ev,
            status="confirmed",
            tests_run=passed,
            evidence=[ev(EvidenceType.log_data, 1), ev(EvidenceType.interview_claim, 2)],
        )
    c = _constraint(
        ev,
        status="confirmed",
        tests_run=passed,
        demand_vs_capacity_checked=True,
        evidence=[ev(EvidenceType.log_data, 1), ev(EvidenceType.interview_claim, 2)],
    )
    assert c.status == "confirmed"


def test_status_change_revalidated(ev):
    c = _constraint(ev)
    with pytest.raises(ValidationError):
        c.status = "confirmed"
