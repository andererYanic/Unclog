"""Weekly team sync (brief §9.6): spread what top performers do, privacy-gated (§14).

Pipeline per task type:
1. privacy gate: no consent reference -> no log mining (works-council / employee notice)
2. pseudonymise people with a per-client salt; drop pods below the minimum size
3. rank people by last week's outcome per task (deterministic)
4. extract the implicit SOP from the top performers' logs (LLM, untrusted-wrapped, PII-scrubbed)
5. propose a skill update: new SKILL.md version, unified diff, release notes
6. report at pod/role level; individual ranking only if the client policy allows it

The update is a proposal: a human approves it before it is pushed to the team.
"""

from __future__ import annotations

import difflib
import hashlib
import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from ..agents.base import load_prompt
from ..ingestion.models import Chunk
from ..ingestion.pii import scrub
from ..ingestion.untrusted import wrap
from ..llm import LLMClient, LLMRequest
from ..llm.types import Message
from ..schemas.delivery import SyncSession

MIN_POD_SIZE = 5


class PrivacyError(PermissionError):
    pass


@dataclass(frozen=True)
class LogEntry:
    person: str
    pod: str
    role: str
    task: str
    text: str


@dataclass(frozen=True)
class Outcome:
    person: str
    task: str
    score: float  # higher = better (the task's agreed result metric)


@dataclass(frozen=True)
class SyncPolicy:
    consent_ref: str | None
    salt: str
    min_pod_size: int = MIN_POD_SIZE
    top_n: int = 2
    share_individual_ranking: bool = False  # explicit client policy only


class ExtractedSOP(BaseModel):
    steps: list[str]
    tips: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    changes_vs_current: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


@dataclass
class SkillUpdate:
    task: str
    old_version: str
    new_version: str
    new_skill: str
    diff: str
    release_notes: str
    sop: ExtractedSOP


@dataclass
class SyncResult:
    session: SyncSession
    updates: list[SkillUpdate] = field(default_factory=list)
    pod_report: str = ""
    suppressed_pods: list[str] = field(default_factory=list)


def pseudonym(person: str, salt: str) -> str:
    return "p-" + hashlib.sha256(f"{salt}:{person}".encode()).hexdigest()[:8]


def _check_privacy(policy: SyncPolicy) -> None:
    if not policy.consent_ref:
        raise PrivacyError(
            "log mining needs a consent/notice reference (works council, "
            "employee notice, legal review): brief §9.6, §14"
        )
    if len(policy.salt) < 16:
        raise PrivacyError("pseudonymisation salt must be ≥ 16 characters and client-specific")


def rank(outcomes: list[Outcome], task: str, salt: str) -> list[tuple[str, float]]:
    scores: dict[str, list[float]] = {}
    for o in outcomes:
        if o.task == task:
            scores.setdefault(pseudonym(o.person, salt), []).append(o.score)
    return sorted(((p, statistics.fmean(v)) for p, v in scores.items()), key=lambda x: -x[1])


def bump(version: str) -> str:
    parts = (version.split(".") + ["0", "0"])[:3]
    major, minor, _ = (int(x) if x.isdigit() else 0 for x in parts)
    return f"{major}.{minor + 1}.0"


def _render_skill(current: str, sop: ExtractedSOP, lang: str) -> str:
    """Replace the procedure section of a SKILL.md with the extracted steps; add tips."""
    head = {
        "de": ("## Ablauf", "## Tipps aus dem Team", "## Fallstricke"),
        "en": ("## Procedure", "## Tips from the team", "## Pitfalls"),
    }[lang]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(sop.steps, 1))
    body = current
    pat = re.compile(rf"{re.escape(head[0])}\n\n.*?(?=\n## |\Z)", re.DOTALL)
    if pat.search(body):
        body = pat.sub(f"{head[0]}\n\n{steps}\n", body, count=1)
    else:
        body = body.rstrip() + f"\n\n{head[0]}\n\n{steps}\n"
    for title, items in ((head[1], sop.tips), (head[2], sop.pitfalls)):
        body = re.sub(rf"\n{re.escape(title)}\n\n.*?(?=\n## |\Z)", "", body, flags=re.DOTALL)
        if items:
            body = body.rstrip() + f"\n\n{title}\n\n" + "\n".join(f"- {t}" for t in items) + "\n"
    return body


def mask_names(text: str, names: set[str], salt: str) -> str:
    """Replace every known team member's name in free text with their pseudonym."""
    for n in sorted(names, key=len, reverse=True):
        if n.strip():
            text = re.sub(
                rf"(?<!\w){re.escape(n)}(?!\w)", pseudonym(n, salt), text, flags=re.IGNORECASE
            )
    return text


def extract_sop(
    llm: LLMClient,
    task: str,
    current_skill: str,
    logs: list[LogEntry],
    salt: str,
    lang: str,
    names: set[str] = frozenset(),
) -> ExtractedSOP:
    chunks = []
    known = set(names) | {e.person for e in logs}
    for i, e in enumerate(logs, 1):
        text, _ = scrub(mask_names(e.text, known, salt))
        chunks.append(
            Chunk(id=f"log-{i}", source_id=pseudonym(e.person, salt), locator=f"ref-{i}", text=text)
        )
    note, body = wrap(chunks)
    prompt = load_prompt("skill_sync")
    req = LLMRequest(
        system=prompt.text,
        agent="skill_sync",
        effort="medium",
        messages=[
            Message(
                role="user",
                content=(
                    f"Language: {lang}. Task: {task}.\nCurrent skill:\n{current_skill}\n\n"
                    f"{note}\nTop-performer logs:\n{body}"
                ),
            )
        ],
    )
    sop = llm.structured(req, ExtractedSOP)
    # defence in depth: nothing personal may leave the sync
    clean = lambda xs: [scrub(mask_names(x, known, salt))[0] for x in xs]  # noqa: E731
    return sop.model_copy(
        update={"steps": clean(sop.steps), "tips": clean(sop.tips), "pitfalls": clean(sop.pitfalls)}
    )


def run_sync(
    llm: LLMClient,
    pod: str,
    logs: list[LogEntry],
    outcomes: list[Outcome],
    skills: dict[str, tuple[str, str]],  # task -> (version, SKILL.md text)
    policy: SyncPolicy,
    on: date,
    lang: Literal["de", "en"] = "de",
) -> SyncResult:
    _check_privacy(policy)
    pod_logs = [e for e in logs if e.pod == pod]
    members = {e.person for e in pod_logs} | {o.person for o in outcomes}
    pod_people = {e.person for e in pod_logs}
    if len(pod_people) < policy.min_pod_size:
        raise PrivacyError(
            f"pod {pod} has {len(pod_people)} people (< {policy.min_pod_size}); "
            "merge pods before reporting"
        )
    updates: list[SkillUpdate] = []
    top_ids: list[str] = []
    report = [f"# {'Team-Sync' if lang == 'de' else 'Team sync'} — {pod} — {on}", ""]
    for task, (version, skill) in sorted(skills.items()):
        ranking = rank([o for o in outcomes if o.person in members], task, policy.salt)
        if len(ranking) < 2:
            report.append(
                f"- {task}: {'zu wenige Ergebnisse' if lang == 'de' else 'too few results'}"
            )
            continue
        top = {p for p, _ in ranking[: policy.top_n]}
        top_ids += sorted(top)
        top_logs = [
            e for e in pod_logs if e.task == task and pseudonym(e.person, policy.salt) in top
        ]
        if not top_logs:
            continue
        sop = extract_sop(llm, task, skill, top_logs, policy.salt, lang, names=members)
        new_version = bump(version)
        new_skill = _render_skill(skill, sop, lang)
        diff = "".join(
            difflib.unified_diff(
                skill.splitlines(keepends=True),
                new_skill.splitlines(keepends=True),
                fromfile=f"{task} v{version}",
                tofile=f"{task} v{new_version}",
            )
        )
        notes = "\n".join(f"- {c}" for c in sop.changes_vs_current) or "- –"
        updates.append(SkillUpdate(task, version, new_version, new_skill, diff, notes, sop))
        scores = [s for _, s in ranking]
        spread = max(scores) - min(scores)
        report += [
            f"## {task}",
            f"- {'Ergebnis-Spanne im Pod' if lang == 'de' else 'result spread in pod'}: "
            f"{min(scores):g}–{max(scores):g} (Δ {spread:g}); n={len(scores)}",
            f"- {'Skill-Vorschlag' if lang == 'de' else 'skill proposal'}: v{version} → "
            f"v{new_version} ({len(sop.changes_vs_current)} changes)",
        ]
        if policy.share_individual_ranking:
            report.append("- ranking: " + ", ".join(f"{p} {s:g}" for p, s in ranking))
    session = SyncSession(
        id=f"sync-{pod}-{on.isoformat()}",
        pod=pod,
        date=on,
        top_performer_ids=sorted(set(top_ids)) if policy.share_individual_ranking else [],
        extracted_sop_ref=None,
        skill_changes=[f"{u.task}: v{u.old_version}->v{u.new_version}" for u in updates],
        consent_ref=policy.consent_ref,
        used_log_mining=True,
    )
    return SyncResult(session, updates, "\n".join(report))
