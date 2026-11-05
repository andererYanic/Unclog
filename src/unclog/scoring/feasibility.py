"""Feasibility & risk checklist (brief §8.4 items 5-9, §14; phase 7).

Deterministic flags, not legal advice. Each flag says what to check and who should check it.
Status: ``ok`` | ``conditional`` (proceed once conditions are met) | ``blocked`` (needs an
expert review before any design work).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..build.library import Pattern
from ..schemas.design import Opportunity, Position, Risk

Severity = Literal["info", "condition", "block"]
DISCLAIMER = {
    "en": "Compliance flags are analysis, not legal advice; confirm with counsel.",
    "de": "Compliance-Hinweise sind Analyse, keine Rechtsberatung; bitte rechtlich prüfen lassen.",
}


@dataclass(frozen=True)
class Flag:
    area: str  # compliance | data | safety | ownership | process | capacity
    severity: Severity
    text: str


@dataclass
class Feasibility:
    opportunity_id: str
    flags: list[Flag] = field(default_factory=list)

    @property
    def status(self) -> str:
        sev = {f.severity for f in self.flags}
        return "blocked" if "block" in sev else "conditional" if "condition" in sev else "ok"

    def risks(self) -> list[Risk]:
        cat = {
            "compliance": "compliance",
            "data": "data",
            "safety": "change",
            "ownership": "change",
            "process": "change",
            "capacity": "change",
        }
        return [
            Risk(
                id=f"feas-{self.opportunity_id}-{i}",
                description=f.text,
                category=cat[f.area],
                likelihood=3 if f.severity == "condition" else 4,
                impact=4 if f.severity == "block" else 3,
                assumption=True,
                confidence=0.6,
            )
            for i, f in enumerate(self.flags, 1)
            if f.severity != "info"
        ]


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile("|".join(rf"\b{w}" for w in words), re.IGNORECASE)


_PERSONAL = _rx(
    "customer",
    "kunde",
    "lead",
    "anfrage",
    "email",
    "e-mail",
    "ticket",
    "contact",
    "kontakt",
    "name",
    "phone",
    "telefon",
    "applicant",
    "bewerb",
    "patient",
)
_EMPLOYMENT = _rx(
    "applicant",
    "bewerb",
    "employee",
    "mitarbeiter",
    "performance",
    "leistung",
    "hiring",
    "recruit",
    "einstell",
    "ranking",
    "top performer",
)
_OUTREACH = _rx(
    "outreach",
    "cold",
    "kaltakquise",
    "newsletter",
    "campaign",
    "kampagne",
    "follow-up",
    "nachfass",
    "call ",
    "anruf",
    "sms",
    "whatsapp",
)
_HEALTH = _rx("patient", "diagnos", "health record", "gesundheit", "medizin", "therap")
_FINANCE = _rx("invoice", "rechnung", "booking", "buchung", "ledger", "payment", "zahlung", "datev")


FLAGS_DE = {
    "Health data:": "Gesundheitsdaten: besondere Kategorie (DSGVO Art. 9; zusätzlich §203 StGB). "
    "Vor jedem Entwurf Prüfung durch Fachleute.",
    "Employment context:": "Beschäftigtenkontext: Hochrisiko-Bereich nach EU AI Act "
    "(Bewerbung/Leistungsbewertung); Mitbestimmung des Betriebsrats "
    "(BetrVG §87 Abs. 1 Nr. 6). Vorher Information/Einwilligung und "
    "rechtliche Prüfung.",
    "Personal data:": "Personenbezogene Daten: Rechtsgrundlage nach DSGVO, "
    "Auftragsverarbeitungsvertrag mit dem KI-Anbieter, Datenminimierung, "
    "Löschfristen.",
    "Marketing outreach:": "Werbliche Ansprache: Einwilligungsregeln für E-Mail und Telefon "
    "(UWG §7); Nachrichten nur als Entwurf zur Freigabe.",
    "Bookkeeping records:": "Buchhaltungsunterlagen: Aufbewahrung und Nachvollziehbarkeit "
    "(GoBD); keine ungeprüften Buchungen.",
    "External effect:": "Wirkung nach außen: nur als Entwurf/pausiert anlegen, ein Mensch gibt "
    "vor Versand oder Veröffentlichung frei; Änderungszusammenfassung "
    "nötig (G13).",
    "No named client owner:": "Keine verantwortliche Person beim Kunden: niemand betreibt es "
    "nach der Übergabe (G12, G15).",
    "Underlying process is broken:": "Zugrunde liegender Prozess ist kaputt: erst reparieren "
    "(§9.8).",
    "Process health not yet assessed": "Zustand des Prozesses noch nicht geprüft (§9.8).",
    "Review load would create": "Prüfaufwand würde einen neuen Engpass erzeugen (G8).",
    "Review happens at the constraint:": "Prüfung findet am Engpass statt: der Nettoeffekt muss "
    "im Pilot positiv sein.",
    "Works after the constraint:": "Arbeitet nach dem Engpass: Fehler hier verschwenden "
    "Engpass-Zeit; starke Prüfung nötig.",
    "R&D:": "F&E: getrennt beauftragen; nicht als Beratungsergebnis verkaufen.",
}


def _german(text: str) -> str:
    if text.startswith("Needs data from "):
        systems = text.removeprefix("Needs data from ").split(":")[0]
        return (
            f"Braucht Daten aus {systems}: heute gibt es nur Datei-Uploads (Entscheidung "
            "003); vor dem Livegang regelmäßigen Export oder Schnittstelle einplanen."
        )
    for prefix, de in FLAGS_DE.items():
        if text.startswith(prefix):
            return de
    return text


def assess(
    opp: Opportunity,
    pattern: Pattern | None = None,
    live_connectors: set[str] = frozenset({"file_drop"}),
    domain: str | None = None,
    lang: str = "en",
) -> Feasibility:
    text = " ".join(
        x or ""
        for x in (opp.title, opp.human_in_loop_design, opp.tech_approach, opp.release_gate_design)
    )
    f = Feasibility(opp.id)
    add = f.flags.append
    if _HEALTH.search(text):
        add(
            Flag(
                "compliance",
                "block",
                "Health data: special-category data (GDPR Art. 9; in DE "
                "also §203 StGB secrecy). Expert review before any design.",
            )
        )
    if _EMPLOYMENT.search(text) or domain == "hr":
        add(
            Flag(
                "compliance",
                "condition",
                "Employment context: EU AI Act high-risk area for "
                "recruitment/worker evaluation; in DE co-determination of the works council "
                "(BetrVG §87(1) no. 6). Notice/consent and legal review first.",
            )
        )
    if _PERSONAL.search(text):
        add(
            Flag(
                "compliance",
                "condition",
                "Personal data: GDPR legal basis, data processing "
                "agreement with the model provider, data minimisation, retention.",
            )
        )
    if _OUTREACH.search(text):
        add(
            Flag(
                "compliance",
                "condition",
                "Marketing outreach: consent rules for email/calls "
                "(in DE UWG §7); keep messages as drafts for human approval.",
            )
        )
    if _FINANCE.search(text) or domain == "finance":
        add(
            Flag(
                "compliance",
                "condition",
                "Bookkeeping records: retention and audit trail "
                "(in DE GoBD); no unreviewed postings.",
            )
        )
    if pattern is not None and pattern.external_effect:
        add(
            Flag(
                "safety",
                "condition",
                "External effect: create as draft/paused, human approves "
                "before anything is sent or published; change summary required (G13).",
            )
        )
    if pattern is not None:
        needs = [s for s in pattern.raw.get("systems", []) if s]
        if needs and live_connectors <= {"file_drop"}:
            add(
                Flag(
                    "data",
                    "condition",
                    f"Needs data from {', '.join(needs)}: only file "
                    "uploads exist today (decision 003); plan a scheduled export or build the "
                    "connector before go-live.",
                )
            )
    if not opp.client_owner:
        add(
            Flag(
                "ownership",
                "block",
                "No named client owner: nobody runs it after handover (G12, G15).",
            )
        )
    if not opp.process_health_ok:
        add(Flag("process", "block", "Underlying process is broken: fix it first (§9.8)."))
    elif any("process health" in a for a in opp.assumptions):
        add(Flag("process", "condition", "Process health not yet assessed (§9.8)."))
    if opp.wip_side_effects and "new constraint" in opp.wip_side_effects:
        add(Flag("capacity", "block", "Review load would create a new constraint (G8)."))
    elif opp.wip_side_effects and "at the constraint" in opp.wip_side_effects:
        add(
            Flag(
                "capacity",
                "condition",
                "Review happens at the constraint: net effect must be positive in the pilot.",
            )
        )
    if opp.position is Position.downstream:
        add(
            Flag(
                "safety",
                "condition",
                "Works after the constraint: errors here waste "
                "constraint time; strong verification needed.",
            )
        )
    if opp.rd_label:
        add(Flag("process", "info", "R&D: scope separately; not sold as a consulting outcome."))
    if lang == "de":
        f.flags = [Flag(x.area, x.severity, _german(x.text)) for x in f.flags]
    return f
