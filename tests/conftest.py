from __future__ import annotations

import pytest

from unclog.schemas import Evidence, EvidenceType


@pytest.fixture
def ev():
    def make(type_: EvidenceType = EvidenceType.log_data, i: int = 1) -> Evidence:
        return Evidence(id=f"ev{i}", source_id="src1", type=type_, locator="row 1-40")

    return make
