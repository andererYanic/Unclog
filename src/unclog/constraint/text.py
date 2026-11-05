"""Deterministic text signals in English and German (brief §17 technique library: "ticket/email
text mining for 'waiting on…'").

This is a transparent first pass: keyword patterns, no model. The Policy & Metrics Auditor and
Constraint Analyst agents (step 7+) refine it with an LLM; these hits are their starting points
and remain the evidence of record (quote + locator).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schemas.diagnosis import DomainName


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


BATCHING = _rx(
    r"\bonce (?:a|per) (?:week|month|day)\b",
    r"\bweekly (?:batch|review|run)\b",
    r"\bin (?:one|a single) (?:block|batch|go)\b",
    r"\bin batches\b",
    r"\bbatched\b",
    r"\bevery (?:monday|tuesday|wednesday|thursday|friday)\b",
    r"\bon (?:mondays|tuesdays|wednesdays|thursdays|fridays)\b",
    r"\b(?:monday|tuesday|wednesday|thursday|friday)s? and (?:monday|tuesday|wednesday|"
    r"thursday|friday)s?\b",
    r"\beinmal (?:pro|die|in der) woche\b",
    r"\bgesammelt\b",
    r"\bim block\b",
    r"\b(?:montags|dienstags|mittwochs|donnerstags|freitags)\b",
)
APPROVAL = _rx(
    r"\bsign[- ]?off\b",
    r"\bneeds? (?:an )?approval\b",
    r"\bmust (?:be )?approve[sd]?\b",
    r"\bapproval (?:from|by)\b",
    r"\bsigns? (?:them|it|every|all)\b",
    r"\bfreigabe\b",
    r"\bgenehmig\w*\b",
    r"\bunterschreib\w*\b",
    r"\babzeichn\w*\b",
)
KPI = _rx(
    r"\bbonus\w*\b",
    r"\bquota\b",
    r"\bkpis?\b",
    r"\btargets?\b",
    r"\bincentive\w*\b",
    r"\bprovision\b",
    r"\bzielvereinbarung\w*\b",
    r"\bpraemie\b",
    r"\bprämie\b",
)
LOCAL_EFFICIENCY = _rx(
    r"\butili[sz]ation\b",
    r"\bauslastung\b",
    r"\bbillable hours?\b",
    r"\bhours billed\b",
    r"\b(?:calls|tickets|emails|units|pieces|quotes|leads|orders) (?:prepared |handled |"
    r"closed |made )?(?:per|a) (?:day|hour|week)\b",
    r"\btickets closed\b",
    r"\bcost per department\b",
    r"\bdepartment budget\b",
    r"\bstückzahl\b",
    r"\bpro stunde\b",
    r"\bstunden (?:abrechnen|verrechnet)\b",
)
EXPEDITE = _rx(
    r"\burgent\w*\b",
    r"\brush(?:ed|ing)?\b",
    r"\bexpedit\w*\b",
    r"\bchas(?:e|ing|ed)\b",
    r"\basap\b",
    r"\bwhere is my order\b",
    r"\bovertime\b",
    r"\bsaturdays?\b",
    r"\bweekends?\b",
    r"\bstill behind\b",
    r"\bdringend\b",
    r"\beilig\w*\b",
    r"\bnachhak\w*\b",
    r"\bsamstag\w*\b",
    r"\büberstunden\b",
    r"\bwochenende\b",
    r"\bhinterher\b",
)
ABSENCE = _rx(
    r"\b(?:is|was|goes|went) (?:off|sick|on (?:vacation|holiday|leave)|away)\b",
    r"\bon (?:vacation|holiday|leave)\b",
    r"\btakes? a day off\b",
    r"\bout sick\b",
    r"\bnothing (?:moves|happens|gets done)\b",
    r"\beverything stops\b",
    r"\b(?:im )?urlaub\b",
    r"\bkrank\b",
    r"\bnichts (?:geht|läuft|passiert)\b",
    r"\bsteht alles\b",
)

#: Words that tie a text to a domain (used to attribute policies and signals).
DOMAIN_KEYWORDS: dict[DomainName, tuple[str, ...]] = {
    DomainName.race_r: (
        "ads",
        "campaign",
        "traffic",
        "visitors",
        "impressions",
        "reichweite",
        "werbung",
        "kampagne",
    ),
    DomainName.race_a: (
        "lead",
        "leads",
        "inquiry",
        "inquiries",
        "enquiry",
        "response",
        "anfrage",
        "anfragen",
        "rückruf",
        "callback",
        "meeting booked",
    ),
    DomainName.race_c: (
        "proposal",
        "quote",
        "quotes",
        "offer",
        "close",
        "closing",
        "deal",
        "angebot",
        "angebote",
        "abschluss",
        "checkout",
    ),
    DomainName.race_e: (
        "renewal",
        "upsell",
        "churn",
        "repeat",
        "referral",
        "verlängerung",
        "kündigung",
    ),
    DomainName.fulfillment: (
        "order",
        "orders",
        "delivery",
        "production",
        "workshop",
        "shipping",
        "project",
        "auftrag",
        "aufträge",
        "lieferung",
        "werkstatt",
        "produktion",
        "versand",
    ),
    DomainName.ops: (
        "schedule",
        "scheduling",
        "shift",
        "machine",
        "planung",
        "schicht",
        "maschine",
    ),
    DomainName.support: (
        "ticket",
        "tickets",
        "support",
        "complaint",
        "refund",
        "reklamation",
        "beschwerde",
        "erstattung",
    ),
    DomainName.finance: (
        "invoice",
        "invoices",
        "payment",
        "collections",
        "rechnung",
        "rechnungen",
        "zahlung",
        "mahnung",
        "buchhaltung",
    ),
    DomainName.hr: ("hire", "hiring", "recruit", "onboarding", "einstellung", "bewerb"),
    DomainName.procurement: ("supplier", "stock", "purchase", "lieferant", "einkauf", "lager"),
    DomainName.product: ("release", "deploy", "code review", "backlog", "sprint"),
    DomainName.it: ("integration", "export", "spreadsheet", "manual entry", "excel"),
    DomainName.legal: ("contract", "contracts", "legal", "compliance", "vertrag", "verträge"),
    DomainName.mgmt: (
        "owner",
        "ceo",
        "managing director",
        "geschäftsführer",
        "chef",
        "inhaber",
        "sign-off",
        "freigabe",
    ),
}


@dataclass(frozen=True)
class TextHit:
    kind: str  # batching | approval | kpi | local_efficiency | expedite | absence
    source_id: str
    locator: str
    quote: str
    domains: tuple[DomainName, ...]


_KINDS = {
    "batching": BATCHING,
    "approval": APPROVAL,
    "kpi": KPI,
    "local_efficiency": LOCAL_EFFICIENCY,
    "expedite": EXPEDITE,
    "absence": ABSENCE,
}


def domains_mentioned(text: str) -> tuple[DomainName, ...]:
    low = text.lower()
    found = []
    for d, words in DOMAIN_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            found.append(d)
    return tuple(found)


def mentions(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(t and re.search(rf"\b{re.escape(t.lower())}\b", low) for t in terms)


def scan(source_id: str, locator: str, text: str) -> list[TextHit]:
    """All signal hits in one text segment, each with the sentence it came from."""
    hits = []
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for sentence in sentences:
        doms = domains_mentioned(sentence)
        for kind, rx in _KINDS.items():
            if rx.search(sentence):
                hits.append(TextHit(kind, source_id, locator, sentence.strip()[:400], doms))
    return hits
