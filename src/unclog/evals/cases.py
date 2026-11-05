"""Synthetic client cases for evaluating the agent organization (brief §18).

A case is a folder under ``evals/cases/<id>/`` with ``case.json`` and optional raw files (e.g.
event-log CSVs) that go through the real ingestion path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from ..flow.graph import FlowGraph
from ..schemas.common import Source, UnclogModel
from ..schemas.diagnosis import FlowEdge, FlowNode, Resource, StageMetric, Task


class SyntheticCase(UnclogModel):
    id: str
    title: str
    kind: str = Field(description="race | backend | mixed")
    traps: list[str] = Field(default_factory=list)
    description: str
    sources: list[Source] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    metrics: list[StageMetric] = Field(default_factory=list)
    raw_files: list[str] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)

    folder: Path | None = Field(None, exclude=True)

    def graph(self) -> FlowGraph | None:
        if not self.nodes:
            return None
        return FlowGraph(self.nodes, self.edges, self.resources, self.tasks)

    def raw_path(self, name: str) -> Path:
        if self.folder is None:
            raise ValueError("case not loaded from disk")
        return self.folder / name


def load_case(folder: str | Path) -> SyntheticCase:
    folder = Path(folder)
    case = SyntheticCase.model_validate_json((folder / "case.json").read_text())
    return case.model_copy(update={"folder": folder})


def load_all(root: str | Path) -> list[SyntheticCase]:
    return [load_case(p.parent) for p in sorted(Path(root).glob("*/case.json"))]
