"""Results Ledger (brief §9.7): before/after per metric, with dates, lag notes and attribution
caveats. A standing deliverable: shows results before the client is asked to pay for more."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..schemas.delivery import ResultsLedgerEntry
from ..store import ClientStore

DEFAULT_CAVEAT = {
    "en": "Correlation in time, not proof of cause; other changes in the period are listed in "
    "the notes.",
    "de": "Zeitlicher Zusammenhang, kein Beweis der Ursache; andere Änderungen im Zeitraum "
    "stehen in den Notizen.",
}


class Ledger:
    def __init__(self, store: ClientStore) -> None:
        self.path = Path(store.root) / "results_ledger.jsonl"
        self.store = store

    def add(self, entry: ResultsLedgerEntry, actor: str) -> ResultsLedgerEntry:
        with self.path.open("a") as f:
            f.write(entry.model_dump_json() + "\n")
        self.store._audit("ledger_add", actor, metric=entry.metric, current=entry.current)
        return entry

    def record(
        self,
        metric: str,
        baseline: float,
        current: float,
        baseline_date: date,
        on: date,
        leading: bool,
        actor: str,
        lag_note: str | None = None,
        caveat: str | None = None,
        lang: str = "en",
        stage_metric_id: str | None = None,
    ) -> ResultsLedgerEntry:
        return self.add(
            ResultsLedgerEntry(
                metric=metric,
                stage_metric_id=stage_metric_id,
                baseline=baseline,
                current=current,
                baseline_date=baseline_date,
                date=on,
                leading=leading,
                lag_note=lag_note,
                attribution_caveat=caveat or DEFAULT_CAVEAT[lang],
            ),
            actor,
        )

    def entries(self) -> list[ResultsLedgerEntry]:
        if not self.path.exists():
            return []
        return [
            ResultsLedgerEntry.model_validate_json(x)
            for x in self.path.read_text().splitlines()
            if x.strip()
        ]

    def latest(self) -> dict[str, ResultsLedgerEntry]:
        out: dict[str, ResultsLedgerEntry] = {}
        for e in sorted(self.entries(), key=lambda e: e.date):
            out[e.metric] = e
        return out

    def to_markdown(self, lang: str = "en", higher_is_better: dict[str, bool] | None = None) -> str:
        hib = higher_is_better or {}
        h = {
            "en": (
                "Metric",
                "Baseline",
                "Current",
                "Change",
                "Since",
                "Type",
                "Notes",
                "leading",
                "lagging",
            ),
            "de": (
                "Kennzahl",
                "Ausgang",
                "Aktuell",
                "Änderung",
                "Seit",
                "Art",
                "Hinweise",
                "Frühindikator",
                "Ergebnis",
            ),
        }[lang]
        out = [f"| {' | '.join(h[:7])} |", "|---|---:|---:|---:|---|---|---|"]
        for m, e in sorted(self.latest().items()):
            change = (e.current - e.baseline) / abs(e.baseline) if e.baseline else 0.0
            good = (change > 0) == hib.get(m, True) if change else None
            mark = "" if good is None else (" ✓" if good else " ✗")
            out.append(
                f"| {m} | {e.baseline:g} | {e.current:g} | {change:+.0%}{mark} | "
                f"{e.baseline_date} | {h[7] if e.leading else h[8]} | "
                f"{e.lag_note or ''} {e.attribution_caveat} |"
            )
        return "\n".join(out)

    def export(self) -> str:
        return json.dumps([json.loads(e.model_dump_json()) for e in self.entries()], indent=2)
