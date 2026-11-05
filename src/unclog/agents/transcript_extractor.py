"""Transcript Extractor (decision 007): call transcript -> verified, structured facts.

The model extracts; code verifies. Every fact must carry a verbatim quote that is found in the
transcript (after whitespace/quote/case normalization), or it is rejected. Numbers that do not
appear in their quote are kept but flagged. Accepted facts become schema records: StageMetric
(``measured=False``, sourced to the transcript), Policy and Evidence (``interview_claim``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from ..ingestion.models import Chunk
from ..ingestion.untrusted import wrap
from ..llm import LLMClient
from ..schemas.common import Evidence, EvidenceType
from ..schemas.diagnosis import DomainName, Policy, PolicyKind, StageMetric
from .base import AgentRun, load_prompt, run_structured

DomainLit = Literal[
    "RACE-R",
    "RACE-A",
    "RACE-C",
    "RACE-E",
    "fulfillment",
    "ops",
    "support",
    "finance",
    "hr",
    "procurement",
    "product",
    "it",
    "legal",
    "mgmt",
    "other",
]


# ---- model-facing schema (kept flat for structured outputs) -------------------------------
class XMetric(BaseModel):
    domain: DomainLit
    name: str
    value: float
    unit: str
    period: str | None = None
    is_estimate: bool = False
    quote: str
    locator: str


class XStep(BaseModel):
    name: str
    domain: DomainLit
    performed_by: str | None = None
    volume_per_week: float | None = None
    touch_time_h: float | None = None
    wait_time_h: float | None = None
    batching: str | None = None
    quote: str
    locator: str


class XPolicy(BaseModel):
    kind: Literal["batch_rule", "approval", "kpi", "incentive", "rule"]
    statement: str
    quote: str
    locator: str


class XProbe(BaseModel):
    probe: Literal["absence", "expedite", "mirage", "ownership", "pain"]
    answer_summary: str
    quote: str
    locator: str


class TranscriptExtraction(BaseModel):
    goal_statement: str | None = None
    unit_of_throughput: str | None = None
    metrics: list[XMetric] = Field(default_factory=list)
    steps: list[XStep] = Field(default_factory=list)
    policies: list[XPolicy] = Field(default_factory=list)
    probes: list[XProbe] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


# ---- verification ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[\"'„“”‚‘’«»`´]", "", t)
    t = re.sub(r"[\s\-–—]+", " ", t)
    return t.strip(" .,;:!?")


def _number_forms(value: float) -> set[str]:
    forms = set()
    candidates = [value]
    if 0 < value < 1:
        candidates.append(round(value * 100, 6))  # 0.09 -> "9" (percent)
    for v in candidates:
        if float(v).is_integer():
            i = int(v)
            forms |= {str(i), f"{i:,}", f"{i:,}".replace(",", ".")}
        else:
            s = f"{v:.6f}".rstrip("0").rstrip(".")
            forms |= {s, s.replace(".", ",")}
    return forms


_NUM_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "twenty": 20,
    "fifty": 50,
    "hundred": 100,
    "eins": 1,
    "ein": 1,
    "eine": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
    "zwölf": 12,
    "zwanzig": 20,
    "fünfzig": 50,
    "hundert": 100,
    "half": 0.5,
    "halbe": 0.5,
    "halben": 0.5,
}


def _parse_num(token: str) -> float | None:
    t = token.rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", t):  # thousands separators
        t = re.sub(r"[.,]", "", t)
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def number_in_quote(value: float, quote: str, is_estimate: bool = False) -> bool:
    q = quote.lower()
    nums = re.findall(r"\d[\d.,]*", q)
    forms = _number_forms(value)
    if any(n.rstrip(".,") in forms for n in nums):
        return True
    if is_estimate:  # a midpoint of a stated range ("40 bis 50" -> 45) counts as visible
        vals = sorted(v for n in nums if (v := _parse_num(n)) is not None)
        if len(vals) >= 2 and vals[0] <= value <= vals[-1]:
            return True
    words = re.findall(r"[a-zäöüß]+", q)
    return any(_NUM_WORDS.get(w) == value for w in words)


@dataclass
class Rejected:
    kind: str
    item: dict
    reason: str


@dataclass
class VerifiedCall:
    source_id: str
    extraction: TranscriptExtraction
    metrics: list[StageMetric]
    policies: list[Policy]
    evidence: dict[str, Evidence]  # fact id -> evidence (metric-1, step-2, policy-1, probe-1)
    steps: list[tuple[str, XStep]]
    rejected: list[Rejected] = field(default_factory=list)
    number_flags: list[str] = field(default_factory=list)

    @property
    def acceptance_rate(self) -> float:
        x = self.extraction
        total = len(x.metrics) + len(x.steps) + len(x.policies) + len(x.probes)
        return 1.0 if total == 0 else 1 - len(self.rejected) / total


def verify(extraction: TranscriptExtraction, chunks: list[Chunk], source_id: str) -> VerifiedCall:
    by_loc = {c.locator: _norm(c.text) for c in chunks}
    whole = " ".join(by_loc.values())
    rejected: list[Rejected] = []
    evidence: dict[str, Evidence] = {}

    def found(quote: str, locator: str) -> bool:
        q = _norm(quote)
        if len(q) < 3:
            return False
        return q in by_loc.get(locator, "") or q in whole

    def ev(fid: str, quote: str, locator: str) -> Evidence:
        e = Evidence(
            id=f"ev-{source_id}-{fid}",
            source_id=source_id,
            type=EvidenceType.interview_claim,
            locator=locator,
            quote=quote,
        )
        evidence[fid] = e
        return e

    metrics: list[StageMetric] = []
    flags: list[str] = []
    for i, m in enumerate(extraction.metrics, 1):
        if not found(m.quote, m.locator):
            rejected.append(Rejected("metric", m.model_dump(), "quote not found in transcript"))
            continue
        fid = f"metric-{i}"
        ev(fid, m.quote, m.locator)
        if not number_in_quote(m.value, m.quote, m.is_estimate):
            flags.append(f'{fid}: value {m.value:g} not visible in quote "{m.quote}"')
        metrics.append(
            StageMetric(
                id=f"{source_id}-{fid}",
                domain_id=DomainName(m.domain).value,
                name=m.name,
                value=m.value,
                unit=m.unit,
                period=m.period or "as stated",
                source_id=source_id,
                measured=False,
            )
        )
    policies: list[Policy] = []
    for i, p in enumerate(extraction.policies, 1):
        if not found(p.quote, p.locator):
            rejected.append(Rejected("policy", p.model_dump(), "quote not found in transcript"))
            continue
        fid = f"policy-{i}"
        kind = PolicyKind(p.kind) if p.kind in PolicyKind.__members__ else PolicyKind.rule
        policies.append(
            Policy(
                id=f"pol-{source_id}-{i}",
                kind=kind,
                statement=p.statement,
                evidence=[ev(fid, p.quote, p.locator)],
            )
        )
    steps: list[tuple[str, XStep]] = []
    for i, s in enumerate(extraction.steps, 1):
        if not found(s.quote, s.locator):
            rejected.append(Rejected("step", s.model_dump(), "quote not found in transcript"))
            continue
        fid = f"step-{i}"
        ev(fid, s.quote, s.locator)
        steps.append((fid, s))
    for i, pr in enumerate(extraction.probes, 1):
        if not found(pr.quote, pr.locator):
            rejected.append(Rejected("probe", pr.model_dump(), "quote not found in transcript"))
            continue
        ev(f"probe-{i}", pr.quote, pr.locator)
    return VerifiedCall(source_id, extraction, metrics, policies, evidence, steps, rejected, flags)


# ---- agent ----------------------------------------------------------------------------------
def extract_call(
    llm: LLMClient,
    chunks: list[Chunk],
    source_id: str,
    lang: Literal["de", "en"] = "de",
    prompt_version: int | None = None,
    min_acceptance: float = 0.7,
) -> AgentRun[VerifiedCall]:
    prompt = load_prompt("transcript_extractor", prompt_version)
    note, body = wrap(chunks)
    user = f"Engagement language: {lang}.\n{note}\n\nTranscript segments:\n{body}"

    def check(x: TranscriptExtraction) -> VerifiedCall:
        v = verify(x, chunks, source_id)
        if v.acceptance_rate < min_acceptance:
            bad = "; ".join(
                f'{r.kind} quote "{r.item.get("quote", "")[:80]}" at {r.item.get("locator")}'
                for r in v.rejected[:8]
            )
            raise ValueError(
                f"{len(v.rejected)} facts have quotes that do not appear verbatim in the "
                f"transcript: {bad}. Copy quotes exactly from the given segment, or drop the "
                "fact."
            )
        return v

    return run_structured(llm, prompt, user, TranscriptExtraction, check)


def review_markdown(v: VerifiedCall, lang: Literal["de", "en"] = "de") -> str:
    """Review sheet for the consultant: what was extracted, with quotes, and what was dropped."""
    L = {
        "de": (
            "Auswertung Gespräch",
            "Zahlen (Schätzungen aus dem Gespräch)",
            "Ablaufschritte",
            "Regeln",
            "Antworten auf Engpass-Fragen",
            "Prüfen: Zahl nicht im Zitat",
            "Verworfen (Zitat nicht im Transkript)",
            "Offene Fragen",
            "Ziel",
            "Einheit",
        ),
        "en": (
            "Call extraction",
            "Numbers (estimates from the call)",
            "Flow steps",
            "Rules",
            "Probe answers",
            "Check: number not in quote",
            "Rejected (quote not in transcript)",
            "Open questions",
            "Goal",
            "Unit",
        ),
    }[lang]
    x = v.extraction
    out = [f"# {L[0]} — {v.source_id}", ""]
    if x.goal_statement:
        out.append(f"**{L[8]}:** {x.goal_statement}")
    if x.unit_of_throughput:
        out.append(f"**{L[9]}:** {x.unit_of_throughput}")
    out += ["", f"## {L[1]}"]
    for m, sm in zip(
        [m for i, m in enumerate(x.metrics, 1) if f"metric-{i}" in v.evidence],
        v.metrics,
        strict=True,
    ):
        out.append(
            f"- [ ] [{sm.domain_id}] {sm.name}: **{sm.value:g} {sm.unit}** "
            f'({sm.period}) — "{m.quote}" @{m.locator}'
        )
    out += ["", f"## {L[2]}"]
    out += [
        f"- [ ] [{s.domain}] {s.name}"
        + (f" ({s.performed_by})" if s.performed_by else "")
        + f' — "{s.quote}" @{s.locator}'
        for _, s in v.steps
    ]
    out += ["", f"## {L[3]}"]
    out += [f'- [ ] {p.kind.value}: {p.statement} — "{p.evidence[0].quote}"' for p in v.policies]
    probes = [(i, p) for i, p in enumerate(x.probes, 1) if f"probe-{i}" in v.evidence]
    out += ["", f"## {L[4]}"]
    out += [f'- [ ] {p.probe}: {p.answer_summary} — "{p.quote}" @{p.locator}' for _, p in probes]
    if v.number_flags:
        out += ["", f"## {L[5]}", *[f"- {f}" for f in v.number_flags]]
    if v.rejected:
        out += ["", f"## {L[6]}"]
        out += [
            f'- {r.kind}: "{r.item.get("quote", "")}" @{r.item.get("locator")}' for r in v.rejected
        ]
    if x.open_questions:
        out += ["", f"## {L[7]}", *[f"- {q}" for q in x.open_questions]]
    return "\n".join(out)
