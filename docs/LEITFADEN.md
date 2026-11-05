# Leitfaden für Berater: ein Mandat mit Unclog

Dieser Leitfaden beschreibt Schritt für Schritt, wie ein Kundenmandat mit Unclog läuft: vom
ersten Gespräch bis zur Übergabe. Sie führen die Gespräche, die Agenten bereiten vor und werten
aus. **Alles, was Unclog erzeugt, ist ein Entwurf.** Vor der Weitergabe an den Kunden prüft immer
ein Mensch.

Ein vollständiges Beispiel mit erfundenem Kunden liegt unter `evals/rehearsal/berger/`
(Generalprobe; Ergebnisse in `output/`, Befunde in `FINDINGS.md`).

---

## 0. Einmalig: Einrichtung

```bash
uv venv && uv pip install -e ".[dev,llm,ingest,reports,security]"
```

- Für Texterkennung in gescannten PDFs: `tesseract` installieren (`apt-get install tesseract-ocr
  tesseract-ocr-deu`).
- Für alle KI-Schritte: `ANTHROPIC_API_KEY` als Umgebungsvariable setzen. Ohne Schlüssel laufen
  alle Rechen- und Prüfschritte, die KI-Schritte nicht.
- Kundendaten liegen unter `clients/<kunde>/` und kommen nie ins Repository.

## 1. Neuer Kunde anlegen

```bash
unclog keygen <kunde> --keys-dir <tresor-ordner>     # Schlüssel für verschlüsselte Uploads
unclog policy <kunde> --raw-days 90 --max-usd 50     # Aufbewahrung und Kostendeckel
```

Vorher mit dem Kunden klären: **Auftragsverarbeitungsvertrag (DSGVO)** und Einverständnis zur
Verarbeitung der Daten. Wenn Mitarbeiterdaten betroffen sind: Betriebsrat einbinden.

## 2. Erstgespräch vorbereiten

```bash
unclog call-plan --lang de > gespraechsleitfaden.md
```

Der Leitfaden geht die RACE-Stufen (Reichweite, Anfragen, Abschluss, Bestandskunden) und danach
die Back-End-Bereiche durch. **Fragen Sie in jeder Stufe nach Zahlen**, oder grenzen Sie ein
("mehr oder weniger als 50?"). Wählen Sie das Problem, das weh tut, nicht das, das gut klingt.

Das Gespräch aufzeichnen und transkribieren (Ergebnis als `.vtt`- oder Textdatei).

## 3. Unterlagen einsammeln und einlesen

Bitten Sie um Exporte: CRM (Anfragen, Angebote), Aufträge **mit Statusverlauf und Zeitstempeln**,
Tickets, Rechnungen, Arbeitsanweisungen. Jedes Format ist in Ordnung: CSV, Excel, PDF (auch
gescannt), Word, PowerPoint, E-Mails.

```bash
unclog ingest <kunde> <ordner-mit-dateien>
unclog sources <kunde>                    # was wurde erkannt?
```

Personenbezogene Daten (E-Mail, Telefon, IBAN) werden beim Einlesen geschwärzt. Die Originale
liegen verschlüsselt im Kundenordner.

## 4. Gespräch auswerten

```bash
unclog extract-call <kunde> <source-id-des-transkripts> --lang de
```

Ergebnis: eine **Prüfliste** unter `clients/<kunde>/reviews/`. Jede Zahl steht mit wörtlichem
Zitat und Zeitstempel da. Erfundene Zitate werden automatisch verworfen. Zahlen, die nicht im
Zitat stehen, sind markiert. **Gehen Sie die Liste durch** und haken Sie ab.

## 5. Ablauf abbilden

**Aus Auftragsverläufen (gemessen):**

```bash
unclog flow-from-log <kunde> <source-id-des-exports> --domain fulfillment --save
```

Für `--domain` gibt es diese Bereiche:
- RACE-Stufen: `RACE-R`, `RACE-A`, `RACE-C`, `RACE-E`
- Back-End: `fulfillment`, `ops`, `support`, `finance`, `hr`, `procurement`, `product`, `it`,
  `legal`, `mgmt`

**Wer macht die Arbeit, wie lange dauert sie (von Hand):** Legen Sie die Datei
`clients/<kunde>/flow/manual.json` an, nach dem Vorbild von
`evals/rehearsal/berger/manual_fragment.json`:
- Personen und Teams mit Stunden pro Woche
- Bearbeitungszeit je Schritt
- optional: wie lange Kunden warten, bevor sie abspringen (`patience_h`)

## 6. Fall zusammenstellen und prüfen

```bash
unclog assemble-case <kunde> --title "Firmenname"
```

Unclog listet **Lücken** auf, statt sie zu erfinden:
- fehlendes Ziel
- Bereiche ohne Daten
- Kapazität im Modell, die nicht zu den Messdaten passt

Schließen Sie die wichtigen Lücken im Folgegespräch.

## 7. Diagnose und Plan

```bash
unclog pipeline --case clients/<kunde>/case --client-id <kunde> --out ergebnis --lang de \
  --with-agents
```

Ohne `--with-agents` (oder ohne API-Schlüssel) entsteht die reine Diagnose. Mit Agenten kommen
der Zielbaum, die KI-Chancen und der Fahrplan dazu. Ergebnis im Ordner `ergebnis/`:

| Datei | Inhalt |
|---|---|
| `01-executive-summary.md` | Ziel, Engpass in einfachen Worten, wichtigste Schritte, Wert, Risiken |
| `02-constraint-report.md` | Last und Kapazität, Bereichs-Übersicht, Engpass mit Tests |
| `03-goal-tree.md` | Zielbaum mit Maßnahmen (verworfene Ideen durchgestrichen) |
| `04-roadmap-dbr.md` | Fahrplan in Wellen, Drum-Buffer-Rope, Kennzahlen |
| `06-opportunity-map.md` | KI-Chancen mit Priorität und verantwortlicher Person |
| `07-value.md` und `.xlsx` | Wert (T/I/OE), Schein-Einsparungen |
| `08-risk-register.md` | Risiken inkl. DSGVO-Hinweise (keine Rechtsberatung) |
| `10-quality-gates.md` | Qualitätsprüfungen G1–G17 |

**So lesen Sie das Ergebnis:**
- **Kein bestätigter Engpass?** Dann wird nur gemessen. Die Schritte stehen in der
  Zusammenfassung.
- **Wirkt ein Bereich schwach, das System ist aber anderswo voll?** Dann würde mehr Nachfrage
  nur die Warteschlange verlängern (Flutungsfalle). Keine Werbemaßnahmen empfehlen.
- **Werte sind Annahmen**, bis ein Pilot sie misst. Nie als Zusage formulieren.

## 8. Prüfen und freigeben

```bash
unclog review <kunde> status ergebnis
unclog review <kunde> approve ergebnis/01-executive-summary.md --reviewer "Ihr Name"
unclog review <kunde> comment 04-roadmap-dbr.md --note "Termin mit Markus klären"
unclog review <kunde> release ergebnis --reviewer "Ihr Name"
```

Wird eine Datei nach der Freigabe geändert, ist die Freigabe ungültig. Erst wenn **alle** Dateien
freigegeben sind, entsteht `RELEASE.json`. Erst dann geht etwas an den Kunden.

Das Gleiche geht im Browser: siehe Abschnitt 11.

## 9. System bauen und übergeben

```bash
unclog package <kunde> <system-id> --template decision-brief --opportunity opp-a3 \
  --owner "Büroleitung" --config config.json --lang de
unclog run-system <kunde> <system-id> --input beispiel.json
unclog outbox <kunde> list
unclog outbox <kunde> approve <id> --actor "Name"
```

**Alles mit Wirkung nach außen** (E-Mails, Anzeigen, Rechnungen) landet als Entwurf im
Postausgang. Gesendet wird erst nach Freigabe.

**Livegang:**

```bash
unclog review <kunde> go-live <system-id> --eval-report <bericht.json> --owner-trained \
  --client-accounts
```

Dafür müssen bestanden sein:
- die Qualitätsmessung (10+ Läufe je Testfall)
- die Übergabe-Prüfung: Runbook, Rollback, Konten des Kunden, geschulte verantwortliche Person

## 10. Laufend: Ergebnisse und Engpass im Blick

```bash
unclog ledger <kunde> add --metric "Wartezeit Aufmaß (h)" --baseline 315 --current 120 \
  --baseline-date 2026-10-01 --date 2026-11-15 --lang de
unclog monitor --weeks wochenwerte.json --constraint inhaber --next werkstatt
unclog buffers --orders offene_auftraege.csv --buffer-h 168 --lang de
```

Meldet `monitor` "constraint_relieved", ist der Engpass gewandert: Diagnose neu starten.

## 11. Weboberfläche

```bash
unclog web --clients-root clients        # dann im Browser http://127.0.0.1:8765
```

Dort sehen Sie Kunden, Ergebnisdateien und Prüfstatus. Sie können freigeben, Änderungen
anfordern, kommentieren und den Postausgang bearbeiten.

---

**Grundsätze, die Unclog erzwingt:**
- erst messen, dann bauen
- nur am Engpass arbeiten
- billige Lösungen ohne KI zuerst
- niemand baut ein System, das beim Kunden keiner verantwortet
- nichts geht ohne menschliche Freigabe nach außen
