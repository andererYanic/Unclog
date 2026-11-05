import json

from unclog.schemas import ENTITIES
from unclog.schemas.export import export


def test_all_entities_export(tmp_path):
    paths = export(tmp_path)
    assert len(paths) == len(ENTITIES)
    for p in paths:
        assert json.loads(p.read_text())["type"] == "object"
