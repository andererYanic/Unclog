"""Call prep: a bilingual call plan for the human consultant (decision 007).

Deterministic, no model call. Starts from the first-call script (brief §9.2, §11) and adds
follow-ups from what is already known:
- domains still ``not_assessed`` -> their script question moves up, marked "no data yet"
- unconfirmed constraint candidates -> absence and expedite probes naming the resource
- flow-capping policies -> "why does this rule exist?" (brief §11.7)
- KPIs rewarding local efficiency -> what behaviour they reward
- a confirmed constraint -> mirage and ownership probes aimed at it
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..constraint.analyst import ConstraintReport
from ..domains.heat import HeatTable
from ..paths import knowledge_dir
from ..schemas.diagnosis import REQUIRED_DOMAINS, ConstraintStatus, ConstraintType, DomainVerdict

Lang = Literal["de", "en"]

_T = {
    "absence": {
        "en": "If {who} took a day off, what would stop? What piles up in front of them?",
        "de": "Wenn {who} einen Tag fehlt: Was steht dann still? Was stapelt sich davor?",
    },
    "expedite": {
        "en": "What do you have to rush or chase around {who}? How often?",
        "de": "Was müssen Sie bei {who} beschleunigen oder nachhaken? Wie oft?",
    },
    "policy": {
        "en": 'You mentioned: "{rule}". Why does this rule exist? What would happen without it, '
        "or with smaller batches?",
        "de": 'Sie erwähnten: "{rule}". Warum gibt es diese Regel? Was wäre ohne sie, oder mit '
        "kleineren Mengen?",
    },
    "kpi": {
        "en": 'About "{rule}": what behaviour does this reward? Does it ever conflict with '
        "getting orders out faster?",
        "de": 'Zu "{rule}": Welches Verhalten belohnt das? Steht es manchmal im Widerspruch '
        "dazu, Aufträge schneller fertig zu bekommen?",
    },
    "mirage": {
        "en": "What would {who} do with one extra hour a day? And what would anyone else do "
        "with one?",
        "de": "Was würde {who} mit einer zusätzlichen Stunde pro Tag machen? Und was jemand "
        "anderes?",
    },
    "owner": {
        "en": "If we change how {what} works, who on your side would own it after we leave?",
        "de": "Wenn wir ändern, wie {what} läuft: Wer bei Ihnen wäre danach dafür verantwortlich?",
    },
    "data": {
        "en": "Data request: {action}",
        "de": "Datenanfrage: {action}",
    },
    "no_data": {"en": "no data yet", "de": "noch keine Daten"},
    "followups": {
        "en": "Follow-ups from what we know so far",
        "de": "Nachfragen aus dem bisherigen Stand",
    },
}


@dataclass(frozen=True)
class PlannedQuestion:
    id: str
    text: str
    why: str = ""
    capture: tuple[str, ...] = ()
    priority: int = 2  # 1 = ask first
    origin: str = "script"  # script | follow-up


@dataclass
class CallSection:
    id: str
    title: str
    questions: list[PlannedQuestion] = field(default_factory=list)


@dataclass
class CallPlan:
    lang: Lang
    sections: list[CallSection]
    note: str

    def questions(self) -> list[PlannedQuestion]:
        return [q for s in self.sections for q in s.questions]

    def to_markdown(self) -> str:
        head = {"en": "# Call plan", "de": "# Gesprächsleitfaden"}[self.lang]
        out = [head, "", f"_{self.note}_"]
        for s in self.sections:
            if not s.questions:
                continue
            out += ["", f"## {s.title}"]
            for q in sorted(s.questions, key=lambda q: q.priority):
                flag = "**[1]** " if q.priority == 1 else ""
                out.append(f"- [ ] {flag}{q.text}")
                if q.why:
                    out.append(f"  - _{q.why}_")
                if q.capture:
                    label = {"en": "capture", "de": "erfassen"}[self.lang]
                    out.append(f"  - {label}: {', '.join(q.capture)}")
        return "\n".join(out)


def load_script(path: Path | None = None) -> dict:
    p = path or knowledge_dir() / "race" / "first_call_script.json"
    return json.loads(p.read_text())


def build_call_plan(
    lang: Lang = "de",
    heat: HeatTable | None = None,
    report: ConstraintReport | None = None,
    script: dict | None = None,
) -> CallPlan:
    script = script or load_script()
    sections = [CallSection(s["id"], s["title"][lang]) for s in script["sections"]]
    by_id = {s.id: s for s in sections}
    missing = set()
    if heat is not None:
        missing = {
            r.domain.value
            for r in heat.rows
            if r.domain in REQUIRED_DOMAINS and r.verdict is DomainVerdict.not_assessed
        }
    for q in script["questions"]:
        prio = 1 if q.get("domain") in missing else 2
        why = q["why"][lang] if q.get("why") else ""
        if prio == 1:
            why = f"{_T['no_data'][lang]}. {why}".strip()
        by_id[q["section"]].questions.append(
            PlannedQuestion(q["id"], q[lang], why, tuple(q.get("capture", [])), prio, "script")
        )

    follow = CallSection("followups", _T["followups"][lang])
    if report is not None:
        _followups(report, lang, follow)
    if follow.questions:
        sections.insert(1, follow)
    return CallPlan(lang, sections, script["note"][lang])


def _client_words(policy) -> str:
    """Quote the client's own words (any language) rather than our internal description."""
    quotes = [e.quote for e in policy.evidence if e.quote]
    return (quotes[-1] if quotes else policy.statement)[:160]


def _followups(report: ConstraintReport, lang: Lang, sec: CallSection) -> None:
    n = 0

    def add(kind: str, why: str = "", **fmt) -> None:
        nonlocal n
        n += 1
        sec.questions.append(
            PlannedQuestion(
                f"fu-{n}", _T[kind][lang].format(**fmt), why, priority=1, origin="follow-up"
            )
        )

    for c in report.candidates:
        if c.type is ConstraintType.physical and c.resource_id:
            add("absence", c.description, who=c.resource_id)
            add("expedite", c.description, who=c.resource_id)
    for p in report.policy_audit.flow_capping():
        add("policy", p.id, rule=_client_words(p))
    for p in report.policy_audit.local_optima():
        if p.kind.value == "kpi":
            add("kpi", p.id, rule=_client_words(p))
    b = report.binding
    if b is not None and b.status is ConstraintStatus.confirmed:
        if b.resource_id:  # mirage probe is about the constraint resource's time (§8.6)
            add("mirage", b.description, who=b.resource_id)
        add("owner", b.description, what=b.description.split(" at ")[0][:80])
    for a in report.discovery_actions[:5]:
        add("data", action=a)
