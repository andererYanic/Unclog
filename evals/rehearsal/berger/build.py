"""Build the rehearsal materials for the fictional 'Schreinerei Holzwerk Berger GmbH'.

Everything here is invented for a dress rehearsal of the workflow. Run:
    python evals/rehearsal/berger/build.py
"""

from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
UP = HERE / "uploads"

TRANSCRIPT = """WEBVTT

00:00:40.000 --> 00:00:52.000
Berger: Unser Ziel ist ganz klar: mehr Küchen und Einbaumöbel verkaufen, und zwar mit vernünftiger Marge.

00:01:05.000 --> 00:01:14.000
Berger: Eine Einheit ist für uns ein Auftrag, also eine Küche oder ein Einbauschrank, der bezahlt ist.

00:02:10.000 --> 00:02:22.000
Berger: Wir kriegen so 50, 60 Anfragen im Monat, das meiste über die Website und über Empfehlungen.

00:03:00.000 --> 00:03:12.000
Berger: Ehrlich gesagt brauchen wir mehr Anfragen. Ich überlege, eine Agentur für Google-Anzeigen zu nehmen.

00:04:20.000 --> 00:04:34.000
Berger: Das Aufmaß mache ich selbst, immer freitags und samstags. Da will ich keinen anderen ranlassen, da passieren sonst Fehler.

00:05:10.000 --> 00:05:20.000
Berger: Im Moment warten bestimmt 20 Kunden auf einen Aufmaßtermin, manche schon drei Wochen.

00:06:00.000 --> 00:06:12.000
Berger: Von den Angeboten, die rausgehen, wird knapp die Hälfte zum Auftrag.

00:07:15.000 --> 00:07:26.000
Berger: Die Werkstatt ist eigentlich nicht voll, die Jungs bauen zwischendurch Lagerware.

00:08:30.000 --> 00:08:40.000
Berger: Wenn ich im Urlaub bin, passiert beim Aufmaß gar nichts, dann stapeln sich die Anfragen.

00:09:05.000 --> 00:09:15.000
Berger: Manche Kunden rufen zwei, drei Mal an und fragen, wann wir endlich kommen.

00:10:20.000 --> 00:10:30.000
Berger: Mein Werkstattleiter Markus könnte das Aufmaß bestimmt auch, der macht das seit zwanzig Jahren.
"""

INSTRUCTION = """# Arbeitsanweisung Vertrieb (Stand 2024)

Jede Anfrage wird im CRM angelegt. Das Aufmaß macht ausschließlich der Inhaber.

Angebote über 8.000 EUR gibt der Inhaber frei. Angebote werden gesammelt montags verschickt.

Kontakt bei Fragen: thomas.berger@holzwerk-berger.example
"""


def event_log(path: Path, seed: int = 3) -> None:
    rng = random.Random(seed)
    start = datetime(2026, 7, 6, 8, 0)
    owner_free = start
    rows = []
    for i in range(1, 12 * 13 + 1):  # ~13 enquiries/week for 12 weeks
        t = start + timedelta(hours=i * 168 / 13 + rng.uniform(-4, 4))
        vid = f"V-{2400 + i}"
        rows.append((vid, "anfrage", t, "buero"))
        if rng.random() > 0.72:
            continue  # no measuring appointment (not a fit, no reply)
        # the owner measures on Fridays/Saturdays: single queue (~6.5 jobs/week in practice)
        slot = max(t + timedelta(hours=24), owner_free) + timedelta(hours=rng.uniform(2, 10))
        owner_free = slot + timedelta(hours=168 / 8.5)
        if slot > datetime(2026, 9, 28):
            continue  # still waiting for a measuring appointment at export time
        rows.append((vid, "aufmass", slot, "inhaber"))
        quote = slot + timedelta(hours=rng.uniform(40, 120))
        rows.append((vid, "angebot_versendet", quote, "buero"))
        if rng.random() > 0.47:
            continue
        order = quote + timedelta(hours=rng.uniform(48, 240))
        rows.append((vid, "auftrag", order, "buero"))
        prod = order + timedelta(hours=rng.uniform(72, 200))
        rows.append((vid, "produktion_start", prod, "werkstatt"))
        rows.append(
            (vid, "montage_fertig", prod + timedelta(hours=rng.uniform(150, 260)), "montage")
        )
    rows.sort(key=lambda r: r[2])
    with path.open("w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["vorgang_id", "status", "zeitpunkt", "bearbeiter"])
        for vid, act, ts, who in rows:
            w.writerow([vid, act, ts.strftime("%d.%m.%Y %H:%M"), who])


def scripted() -> dict:
    """Fixed model answers for the AI steps (no API key yet). Quotes are verbatim from the
    transcript, so the real quote verification runs on them."""
    q = lambda loc, text: {"quote": text, "locator": loc}  # noqa: E731
    extraction = {
        "goal_statement": "Mehr Küchen und Einbaumöbel mit vernünftiger Marge verkaufen",
        "unit_of_throughput": "bezahlter Auftrag (Küche oder Einbauschrank)",
        "metrics": [
            {
                "domain": "RACE-A",
                "name": "Anfragen",
                "value": 55,
                "unit": "pro Monat",
                "period": "Monat",
                "is_estimate": True,
                **q("t=00:02:10.000", "Wir kriegen so 50, 60 Anfragen im Monat"),
            },
            {
                "domain": "RACE-C",
                "name": "Kunden wartend auf Aufmaß",
                "value": 20,
                "unit": "Kunden",
                "period": "aktuell",
                "is_estimate": True,
                **q("t=00:05:10.000", "Im Moment warten bestimmt 20 Kunden auf einen Aufmaßtermin"),
            },
            {
                "domain": "RACE-C",
                "name": "Angebot -> Auftrag",
                "value": 0.5,
                "unit": "ratio",
                "period": "laufend",
                "is_estimate": True,
                **q("t=00:06:00.000", "knapp die Hälfte zum Auftrag"),
            },
        ],
        "steps": [
            {
                "name": "Aufmaß",
                "domain": "RACE-C",
                "performed_by": "Inhaber",
                "batching": "freitags und samstags",
                **q("t=00:04:20.000", "Das Aufmaß mache ich selbst, immer freitags und samstags."),
            },
        ],
        "policies": [
            {
                "kind": "rule",
                "statement": "Nur der Inhaber macht das Aufmaß",
                **q("t=00:04:20.000", "Da will ich keinen anderen ranlassen"),
            },
        ],
        "probes": [
            {
                "probe": "absence",
                "answer_summary": "Ohne Inhaber kein Aufmaß",
                **q("t=00:08:30.000", "Wenn ich im Urlaub bin, passiert beim Aufmaß gar nichts"),
            },
            {
                "probe": "expedite",
                "answer_summary": "Kunden fragen mehrfach nach",
                **q("t=00:09:05.000", "Manche Kunden rufen zwei, drei Mal an"),
            },
            {
                "probe": "ownership",
                "answer_summary": "Werkstattleiter könnte Aufmaß übernehmen",
                **q(
                    "t=00:10:20.000", "Mein Werkstattleiter Markus könnte das Aufmaß bestimmt auch"
                ),
            },
        ],
        "open_questions": [
            "Wie lange dauert ein Aufmaß inkl. Fahrt?",
            "Wie viele Stunden pro Woche hat der Inhaber für Aufmaße?",
        ],
        "confidence": 0.75,
    }
    N = lambda i, p, st, tag="non_ai", step="exploit", link="acts_on", days=2: {  # noqa: E731
        "id": i,
        "parent_id": p,
        "statement": st,
        "kind": "base_action",
        "constraint_link": link,
        "focus_step": step,
        "tag": tag,
        "effort_days": days,
    }
    tree = {
        "nodes": [
            N(
                "a1",
                "opt-policy",
                "Werkstattleiter Markus übernimmt nach 2 begleiteten Terminen "
                "die Hälfte der rund 9 Aufmaße pro Woche",
                days=5,
            ),
            N(
                "a2",
                "opt-exploit-idle",
                "Aufmaßtermine auch dienstags und donnerstags anbieten "
                "statt nur freitags und samstags",
                days=1,
            ),
            N(
                "a3",
                "opt-exploit-quality",
                "Vor jedem Aufmaß Fotos, Grundriss und Budget vom "
                "Kunden einholen und als Vorlage vorbereiten "
                "(ca. 9 Vorlagen pro Woche)",
                tag="ai_doable",
                link="protects",
                days=4,
            ),
            N(
                "a4",
                "opt-subordinate",
                "Keine Google-Anzeigen schalten, solange mehr als 10 Kunden auf ein Aufmaß warten",
                step="subordinate",
                link="gates_flow",
                days=1,
            ),
            N(
                "a5",
                "opt-elevate",
                "Zweiten Aufmaß-Laser und Tablet-Aufmaß-App für Markus "
                "anschaffen (Aufmaß 2 h -> 1,5 h)",
                tag="human",
                step="elevate",
                days=5,
            ),
            N(
                "x1",
                "root",
                "KI-Chatbot auf der Website für mehr Anfragen",
                tag="ai_doable",
                link="off_constraint",
                days=5,
            ),
        ],
        "open_questions": [],
        "confidence": 0.7,
    }
    sc = {"score": 4, "justification": "vorbereitete Vorlagen verkürzen jedes Aufmaß"}
    analyst = {
        "judgements": [
            {
                "seed_id": "a3",
                "pattern_id": "constraint-prestaging",
                "title": "Aufmaß-Vorlage aus Kundenfotos, Grundriss und Budget für ca. 9 Termine pro "
                "Woche aus dem CRM vorbereiten",
                "ai_role": "assist",
                "human_in_loop_design": "Büro prüft jede Vorlage vor dem Termin; der Aufmesser "
                "korrigiert vor Ort",
                "release_gate_design": "genau eine Vorlage je bestätigtem Termin, nicht mehr",
                "items_per_week": 9,
                "review_minutes_per_item": 5,
                "reviewer_resource_id": "buero",
                "output_verification": "Aufmesser bestätigt Maße vor Ort",
                "cost_of_error": "medium",
                "client_owner_role": "Büroleitung",
                "tech_approach": "CRM-Export + Fotos + Prompt",
                "build_vs_buy": "build",
                "risks": [
                    {
                        "description": "Kundenfotos enthalten personenbezogene Daten",
                        "category": "compliance",
                        "likelihood": 3,
                        "impact": 2,
                        "mitigation": "Löschfrist, AV-Vertrag mit Anbieter",
                    }
                ],
                "scores": {
                    k: sc
                    for k in (
                        "throughput_impact",
                        "feasibility",
                        "data_readiness",
                        "risk",
                        "effort",
                        "strategic_fit",
                    )
                },
            }
        ],
        "open_questions": ["Gibt es eine Fotofunktion im Anfrageformular?"],
        "confidence": 0.7,
    }
    return {"extraction": extraction, "tree": tree, "analyst": analyst}


MANUAL_FRAGMENT = {
    "resources": [
        {
            "id": "inhaber",
            "name": "Thomas Berger (Inhaber)",
            "kind": "person",
            "count": 1,
            "hours_per_period": 18,
            "assumption": True,
            "confidence": 0.6,
        },
        {
            "id": "buero",
            "name": "Büro",
            "kind": "person",
            "count": 1,
            "hours_per_period": 30,
            "assumption": True,
            "confidence": 0.6,
        },
        {
            "id": "werkstatt",
            "name": "6 Schreiner",
            "kind": "team",
            "count": 6,
            "hours_per_period": 38,
            "assumption": True,
            "confidence": 0.7,
        },
        {
            "id": "montage",
            "name": "2 Monteure",
            "kind": "team",
            "count": 2,
            "hours_per_period": 38,
            "assumption": True,
            "confidence": 0.7,
        },
    ],
    "nodes": [
        {"id": "log-anfrage", "name": "Anfrage", "domain_id": "RACE-A"},
        {
            "id": "log-aufmass",
            "name": "Aufmaß",
            "domain_id": "RACE-C",
            "resource_ids": ["inhaber"],
            "patience_h": 504,  # "manche schon drei Wochen": customers give up after ~3 weeks
            "service": {"kind": "lognormal", "params": {"mean": 2.8, "cv": 0.3}, "unit": "hour"},
        },
        {
            "id": "log-angebot-versendet",
            "name": "Angebot",
            "domain_id": "RACE-C",
            "resource_ids": ["buero"],
            "service": {"kind": "lognormal", "params": {"mean": 1.5, "cv": 0.4}, "unit": "hour"},
        },
        {"id": "log-auftrag", "name": "Auftrag", "domain_id": "RACE-C"},
        {
            "id": "log-produktion-start",
            "name": "Produktion",
            "domain_id": "fulfillment",
            "resource_ids": ["werkstatt"],
            "service": {"kind": "lognormal", "params": {"mean": 40, "cv": 0.3}, "unit": "hour"},
        },
        {
            "id": "log-montage-fertig",
            "name": "Montage",
            "domain_id": "fulfillment",
            "resource_ids": ["montage"],
            "service": {"kind": "lognormal", "params": {"mean": 12, "cv": 0.3}, "unit": "hour"},
        },
    ],
}


if __name__ == "__main__":
    UP.mkdir(parents=True, exist_ok=True)
    (UP / "erstgespraech.vtt").write_text(TRANSCRIPT)
    (UP / "arbeitsanweisung_vertrieb.md").write_text(INSTRUCTION)
    event_log(UP / "auftragsverlauf.csv")
    (HERE / "scripted_answers.json").write_text(
        json.dumps(scripted(), indent=2, ensure_ascii=False)
    )
    (HERE / "manual_fragment.json").write_text(
        json.dumps(MANUAL_FRAGMENT, indent=2, ensure_ascii=False)
    )
    print("rehearsal materials written")
