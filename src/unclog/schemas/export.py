"""Export JSON Schemas for every core entity: ``unclog-export-schemas [outdir]``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import ENTITIES


def export(outdir: str | Path) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in sorted(ENTITIES.items()):
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "schemas"
    paths = export(target)
    print(f"wrote {len(paths)} schemas to {target}/")


if __name__ == "__main__":
    main()
