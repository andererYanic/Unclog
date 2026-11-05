"""Message catalog for diagnosis output (German / English).

Analysis code produces client-facing sentences (heat-table rationale, constraint descriptions,
test notes, policy findings). They all go through ``t()`` so reports come out in the engagement
language. Unknown languages fall back to English.
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    # ---- heat table -------------------------------------------------------------------------
    "cov_not_assessed": {"en": "{d}: not assessed ({why})", "de": "{d}: nicht bewertet ({why})"},
    "cov_clear_noev": {
        "en": "{d}: 'clear' without metric or evidence",
        "de": "{d}: 'unauffällig' ohne Kennzahl oder Beleg",
    },
    "cov_no_flow": {
        "en": "both-direction (demand vs capacity) check not possible: no flow data",
        "de": "Prüfung Nachfrage gegen Kapazität nicht möglich: kein Ablaufmodell",
    },
    "dir_no_graph": {
        "en": "No flow graph; cannot compare demand with capacity.",
        "de": "Kein Ablaufmodell; Nachfrage und Kapazität nicht vergleichbar.",
    },
    "dir_no_load": {
        "en": "Flow graph has no resource load (missing service times?).",
        "de": "Ablaufmodell ohne Ressourcenlast (fehlen Bearbeitungszeiten?).",
    },
    "where_backend": {"en": "back-end", "de": "Back-End"},
    "where_front": {"en": "front-end (RACE)", "de": "Front-End (RACE)"},
    "dir_cap": {
        "en": "{r} ({where}, {dom}) is at {u} of capacity.",
        "de": "{r} ({where}, {dom}) ist zu {u} ausgelastet.",
    },
    "flood": {
        "en": " More leads/demand will only lengthen the queue (flooding trap); do not "
        "recommend growth work until this is relieved.",
        "de": " Mehr Anfragen oder Nachfrage verlängern nur die Warteschlange "
        "(Flutungsfalle); keine Wachstumsmaßnahmen, bevor das gelöst ist.",
    },
    "dir_market": {
        "en": "Capacity is ample (busiest resource {r} at {u}; +{h} demand possible). No resource "
        "is the limit: look at demand (RACE stages) and at rules that hold work back.",
        "de": "Kapazität reicht (am stärksten ausgelastet: {r} mit {u}; +{h} Nachfrage möglich). "
        "Keine Ressource ist die Grenze: Nachfrage (RACE-Stufen) und Regeln prüfen, die Arbeit "
        "aufhalten.",
    },
    "dir_inconclusive": {
        "en": "Busiest resource {r} at {u}: near capacity but not over. Needs "
        "queue evidence or simulation (step 6).",
        "de": "Am stärksten ausgelastet: {r} mit {u}: nahe an der Grenze, aber "
        "nicht darüber. Belege zu Warteschlangen oder Simulation nötig.",
    },
    "gap_x": {"en": "{x}x the benchmark", "de": "{x}-fach über dem Richtwert"},
    "gap_pct": {"en": "{p} worse", "de": "{p} schlechter"},
    "estimate": {"en": " [estimate]", "de": " [Schätzung]"},
    "sig_conv": {
        "en": "{name} = {v} {unit} vs benchmark {b} ({how}){est}",
        "de": "{name} = {v} {unit} gegen Richtwert {b} ({how}){est}",
    },
    "sig_cap": {
        "en": "{r} at {u} of capacity ({load} of {cap} h/week)",
        "de": "{r} zu {u} ausgelastet ({load} von {cap} h/Woche)",
    },
    "queued": {"en": "{q} queued", "de": "{q} in der Warteschlange"},
    "wait": {"en": "~{w} h wait", "de": "~{w} h Wartezeit"},
    "sig_log_wait": {
        "en": "median {w} h wait before '{a}' (p90 {p90} h, {n} cases, event log)",
        "de": "Median {w} h Wartezeit vor '{a}' (p90 {p90} h, {n} Fälle, Ereignisprotokoll)",
    },
    "sig_backlog": {
        "en": "backlog growing: {i} cases/week in vs {o} out; {open} open vs ~{exp} "
        "expected (event log; check export edge effects)",
        "de": "Rückstand wächst: {i} Fälle/Woche rein gegen {o} raus; {open} offen "
        "gegen ~{exp} erwartet (Ereignisprotokoll; Randeffekte des Exports "
        "prüfen)",
    },
    "max_util": {"en": "max utilization {u}", "de": "max. Auslastung {u}"},
    "no_signal": {"en": "No signal above thresholds", "de": "Kein Signal über den Schwellen"},
    "only_estimates": {
        "en": "Only unsourced estimates; verify with data before dismissing",
        "de": "Nur unbelegte Schätzungen; vor dem Ausschließen mit Daten prüfen",
    },
    "no_data": {
        "en": "No metrics or flow data yet",
        "de": "Noch keine Kennzahlen oder Ablaufdaten",
    },
    # ---- heat table markdown ------------------------------------------------------------------
    "heat_header": {
        "en": "| Rank | Domain | Prior | Signals | Max util. | Score | Verdict | Key evidence |",
        "de": "| Rang | Bereich | Prior | Signale | Max. Ausl. | Score | Urteil | "
        "Wichtigste Belege |",
    },
    "verdict_candidate": {"en": "candidate", "de": "Kandidat"},
    "verdict_clear": {"en": "clear", "de": "unauffällig"},
    "verdict_not_assessed": {"en": "not assessed", "de": "nicht bewertet"},
    "verdict_constraint": {"en": "CONSTRAINT", "de": "ENGPASS"},
    "demand_vs_capacity": {"en": "Demand vs capacity", "de": "Nachfrage gegen Kapazität"},
    "coverage_gaps": {"en": "Coverage gaps (G5)", "de": "Abdeckungslücken (G5)"},
    # ---- constraint hypotheses ------------------------------------------------------------------
    "cand_physical": {
        "en": "{name} ({rid}) at {u} of capacity in {d}",
        "de": "{name} ({rid}) zu {u} ausgelastet in {d}",
    },
    "cand_policy": {"en": "Policy: {s}", "de": "Regel: {s}"},
    "cand_market": {
        "en": "Market: demand/conversion at {d} limits throughput while capacity is ample",
        "de": "Markt: Nachfrage/Konversion in {d} begrenzt den Durchsatz, obwohl "
        "Kapazität frei ist",
    },
    "note_contradict": {
        "en": "internal queues at {x} contradict a market constraint",
        "de": "interne Warteschlangen in {x} widersprechen einem Marktengpass",
    },
    "note_estimates_only": {
        "en": "stage located only by estimates; needs measured stage data",
        "de": "Stufe nur durch Schätzungen verortet; Messdaten der Stufe nötig",
    },
    "next_physical": {
        "en": "After relief, {r} is the busiest other resource at {u}; watch its queue.",
        "de": "Nach der Entlastung ist {r} mit {u} die am stärksten ausgelastete "
        "übrige Ressource; Warteschlange beobachten.",
    },
    "next_market_saturates": {
        "en": "If demand grows ~{h}, {r} saturates first.",
        "de": "Wächst die Nachfrage um ~{h}, ist {r} zuerst voll.",
    },
    "next_market": {
        "en": "After relief, capacity is ample: expect the market (RACE) to become "
        "the constraint (~{h} demand headroom). Re-run Step 1.",
        "de": "Nach der Entlastung reicht die Kapazität: Der Markt (RACE) wird "
        "voraussichtlich zum Engpass (~{h} Nachfrage-Spielraum). Schritt 1 neu "
        "durchführen.",
    },
    # ---- confirmation tests ---------------------------------------------------------------------
    "t_cap_plus": {"en": "+{p} capacity at {r}", "de": "+{p} Kapazität bei {r}"},
    "t_demand_plus": {"en": "+{p} demand", "de": "+{p} Nachfrage"},
    "t_not_saturated": {
        "en": " (resource not saturated: extra capacity adds nothing)",
        "de": " (Ressource nicht voll: mehr Kapazität bringt nichts)",
    },
    "t_saturates": {
        "en": " (a resource saturates: demand is not the only limit)",
        "de": " (eine Ressource läuft voll: die Nachfrage ist nicht die einzige Grenze)",
    },
    "t_relief": {
        "en": "{what}: throughput {a} -> {b} units/week{why}",
        "de": "{what}: Durchsatz {a} -> {b} Einheiten/Woche{why}",
    },
    "t_sim_relief": {
        "en": "simulated {what}: throughput {a} -> {b} ({g}, {n} replications)",
        "de": "simuliert {what}: Durchsatz {a} -> {b} ({g}, {n} Läufe)",
    },
    "t_idle_busiest": {
        "en": "busiest resource {r} at {u}",
        "de": "am stärksten ausgelastet: {r} mit {u}",
    },
    "t_idle_none": {"en": "no loaded resources", "de": "keine ausgelasteten Ressourcen"},
    "t_idle_ok": {
        "en": "; no internal queues -> capacity idles waiting for demand",
        "de": "; keine internen Warteschlangen -> Kapazität wartet auf Nachfrage",
    },
    "t_idle_waits": {"en": "; internal waits at {x}", "de": "; interne Wartezeiten bei {x}"},
    "t_starve": {"en": "downstream of {r} ({u}): {detail}", "de": "nach {r} ({u}): {detail}"},
    "t_starved": {"en": " -> starved/idle capacity", "de": " -> Kapazität wartet/leer"},
    "t_busier": {
        "en": " -> a downstream resource is busier",
        "de": " -> eine nachgelagerte Ressource ist stärker ausgelastet",
    },
    "t_queue_none": {
        "en": "no queue or long wait observed in front of the candidate",
        "de": "keine Warteschlange oder lange Wartezeit vor dem Kandidaten",
    },
    "t_queue_longer": {
        "en": " (but a longer wait exists at {n}: ~{w} h)",
        "de": " (aber längere Wartezeit bei {n}: ~{w} h)",
    },
    "t_log_wait": {
        "en": "event log: median {w} h wait before '{a}' (p90 {p90} h, n={n})",
        "de": "Ereignisprotokoll: Median {w} h Wartezeit vor '{a}' (p90 {p90} h, n={n})",
    },
    "t_statements": {"en": '{n} statement(s), e.g. "{q}"', "de": '{n} Aussage(n), z. B. "{q}"'},
    # ---- policy audit ---------------------------------------------------------------------------
    "pol_batch": {
        "en": "'{node}' releases work in batches of ~{b}; items wait ~{w} h",
        "de": "'{node}' gibt Arbeit in Losen von ~{b} frei; Vorgänge warten ~{w} h",
    },
    "pol_batch_rewards": {
        "en": "fewer context switches for the team (local efficiency)",
        "de": "weniger Wechsel für das Team (lokale Effizienz)",
    },
    "pol_batch_rec": {
        "en": "Release work continuously or in much smaller transfer batches; "
        "measure the wait before and after.",
        "de": "Arbeit laufend oder in viel kleineren Mengen weitergeben; Wartezeit "
        "vorher und nachher messen.",
    },
    "pol_rule_found": {"en": "Rule found:", "de": "Gefundene Regel:"},
    "pol_local_rewards": {
        "en": "local efficiency (keeping resources busy) rather than system throughput",
        "de": "lokale Effizienz (Ressourcen beschäftigt halten) statt Durchsatz des Ganzen",
    },
    "pol_replace": {"en": "Replace with: {x}", "de": "Ersetzen durch: {x}"},
    "pol_challenge": {
        "en": "Ask why it exists and what happens without it (brief §11.7); test "
        "removing or shrinking it before automating around it (brief §2.4.8).",
        "de": "Fragen, warum es sie gibt und was ohne sie passiert; Abschaffen "
        "oder Verkleinern testen, bevor darum herum automatisiert wird.",
    },
    "kpi_replacements": {
        "en": "constraint throughput (units/week through the binding "
        "constraint); lead time (order to cash, median and p90); "
        "due-date performance",
        "de": "Durchsatz am Engpass (Einheiten/Woche); Durchlaufzeit (Auftrag "
        "bis Geld, Median und p90); Termintreue",
    },
    # ---- constraint report markdown -------------------------------------------------------------
    "rep_binding": {
        "en": "Binding constraint ({t}, {d}) — confirmed",
        "de": "Engpass ({t}, {d}) — bestätigt",
    },
    "rep_conf_tests": {"en": "Confidence {c}. Tests:", "de": "Konfidenz {c}. Tests:"},
    "rep_pass": {"en": "pass", "de": "bestanden"},
    "rep_fail": {"en": "fail", "de": "nicht bestanden"},
    "rep_none": {"en": "No confirmed constraint yet", "de": "Noch kein bestätigter Engpass"},
    "rep_g4": {
        "en": "Work is limited to discovery actions until a constraint is confirmed (G4).",
        "de": "Bis ein Engpass bestätigt ist, sind nur Mess- und Erhebungsschritte erlaubt (G4).",
    },
    "rep_next": {"en": "Predicted next constraint", "de": "Voraussichtlich nächster Engpass"},
    "rep_others": {"en": "Other candidates", "de": "Weitere Kandidaten"},
    "rep_unresolved": {"en": "Unresolved signals", "de": "Ungeklärte Signale"},
    "rep_local": {
        "en": "Policies / KPIs rewarding local efficiency",
        "de": "Regeln / Kennzahlen, die lokale Effizienz belohnen",
    },
    "rep_discovery": {"en": "Discovery actions", "de": "Mess- und Erhebungsschritte"},
}


def t(key: str, lang: str = "en", **kw: object) -> str:
    entry = MESSAGES[key]
    return entry.get(lang, entry["en"]).format(**kw)


MESSAGES.update(
    {
        "status_candidate": {"en": "candidate", "de": "Kandidat"},
        "status_confirmed": {"en": "confirmed", "de": "bestätigt"},
        "status_broken": {"en": "broken", "de": "aufgelöst"},
        "status_moved": {"en": "moved", "de": "verschoben"},
        "type_physical": {"en": "resource", "de": "Ressource"},
        "type_policy": {"en": "policy", "de": "Regel"},
        "type_market": {"en": "market", "de": "Markt"},
        "type_paradigm": {"en": "paradigm", "de": "Denkweise"},
        "conf": {"en": "confidence", "de": "Konfidenz"},
    }
)

DOMAIN_LABELS: dict[str, dict[str, str]] = {
    "RACE-R": {"en": "RACE-R (reach)", "de": "RACE-R (Reichweite)"},
    "RACE-A": {"en": "RACE-A (acquire)", "de": "RACE-A (Anfragen)"},
    "RACE-C": {"en": "RACE-C (convert)", "de": "RACE-C (Abschluss)"},
    "RACE-E": {"en": "RACE-E (expand)", "de": "RACE-E (Bestandskunden)"},
    "fulfillment": {"en": "fulfillment", "de": "Auftragsabwicklung"},
    "ops": {"en": "operations", "de": "Betrieb/Produktion"},
    "support": {"en": "support", "de": "Kundenservice"},
    "finance": {"en": "finance", "de": "Finanzen"},
    "hr": {"en": "HR", "de": "Personal"},
    "procurement": {"en": "procurement", "de": "Einkauf"},
    "product": {"en": "product/engineering", "de": "Produkt/Entwicklung"},
    "it": {"en": "IT/data", "de": "IT/Daten"},
    "legal": {"en": "legal/compliance", "de": "Recht/Compliance"},
    "mgmt": {"en": "management", "de": "Führung/Entscheidungen"},
    "other": {"en": "other", "de": "Sonstiges"},
}


def domain_label(domain: str, lang: str = "en") -> str:
    """Display name for a DomainName value (identifiers stay English in data)."""
    entry = DOMAIN_LABELS.get(domain)
    return entry.get(lang, entry["en"]) if entry else domain


def verdict_label(verdict: str, lang: str = "en") -> str:
    return t("verdict_" + verdict, lang)


def num(x: float, lang: str = "en", digits: int = 0) -> str:
    """Number with thousands separators; German uses '.' for thousands and ',' for decimals."""
    s = f"{x:,.{digits}f}"
    if lang == "de":
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return s
