import pytest
from pydantic import ValidationError

from unclog.schemas import EvidenceType, Process, ProcessHealth


def test_ungrounded_entity_rejected():
    with pytest.raises(ValidationError, match="evidence"):
        Process(id="p1", name="Refunds", process_health=ProcessHealth.sound)


def test_assumption_requires_confidence():
    with pytest.raises(ValidationError, match="confidence"):
        Process(id="p1", name="Refunds", process_health=ProcessHealth.sound, assumption=True)
    p = Process(
        id="p1", name="Refunds", process_health=ProcessHealth.sound, assumption=True, confidence=0.4
    )
    assert p.assumption


def test_evidence_grounds_entity(ev):
    p = Process(id="p1", name="Refunds", process_health="broken", evidence=[ev()])
    assert p.evidence_types() == {EvidenceType.log_data}


def test_extra_fields_forbidden(ev):
    with pytest.raises(ValidationError):
        Process(id="p1", name="x", process_health="sound", evidence=[ev()], hours_saved=10)


def test_bad_id_rejected(ev):
    with pytest.raises(ValidationError):
        Process(id="has space", name="x", process_health="sound", evidence=[ev()])
