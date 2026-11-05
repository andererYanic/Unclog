> ENTWURF — vor Weitergabe an den Kunden durch einen Menschen zu prüfen (Brief §16).

# Engpass-Bericht — Schreinerei Holzwerk Berger GmbH

## Last und Kapazität
| Ressource | Last/Woche | Kapazität/Woche | Auslastung |
|---|---:|---:|---:|
| inhaber | 25 h | 18 h | 140% |
| werkstatt | 161 h | 228 h | 71% |
| montage | 48 h | 76 h | 63% |
| buero | 13 h | 30 h | 45% |


## Bereichs-Übersicht (RACE + Back-End)

| Rang | Bereich | Prior | Signale | Max. Ausl. | Score | Urteil | Wichtigste Belege |
|---:|---|---:|---|---:|---:|---|---|
| 1 | RACE-C (Abschluss) | 0.15 | capacity, queue | 140% | 4.15 | Kandidat | inhaber zu 140% ausgelastet (25 von 18 h/Woche); Aufmaß: 46 in der Warteschlange, ~315 h Wartezeit; Angebot: ~74 h Wartezeit; Auftrag: ~162 h Wartezeit; Median 315 h Wartezeit vor 'aufmass' (p90 615 h, 76 Fälle, Ereignisprotokoll); Rückstand wächst: 13,0 Fälle/Woche rein gegen 2,2 raus; 122 offen gegen ~11 erwartet (Ereignisprotokoll; Randeffekte des Exports prüfen) |
| 2 | Auftragsabwicklung | 0.04 | queue | 71% | 2.04 | Kandidat | Produktion: ~130 h Wartezeit; Montage: ~208 h Wartezeit |
| 3 | RACE-R (Reichweite) | 0.15 | – | – | 0.15 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 4 | RACE-A (Anfragen) | 0.15 | – | – | 0.15 | unauffällig | Kein Signal über den Schwellen |
| 5 | RACE-E (Bestandskunden) | 0.15 | – | – | 0.15 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 6 | Betrieb/Produktion | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 7 | Kundenservice | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 8 | Finanzen | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 9 | Personal | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 10 | Einkauf | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 11 | Produkt/Entwicklung | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 12 | IT/Daten | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 13 | Recht/Compliance | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 14 | Führung/Entscheidungen | 0.04 | – | – | 0.04 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |
| 15 | Sonstiges | 0.02 | – | – | 0.02 | nicht bewertet | Noch keine Kennzahlen oder Ablaufdaten |

**Nachfrage gegen Kapazität:** capacity_limited. inhaber (Front-End (RACE), RACE-C) ist zu 140% ausgelastet.

**Abdeckungslücken (G5):**
- RACE-R (Reichweite): nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- RACE-E (Bestandskunden): nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Betrieb/Produktion: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Kundenservice: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Finanzen: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Personal: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Einkauf: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Produkt/Entwicklung: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- IT/Daten: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Recht/Compliance: nicht bewertet (noch keine kennzahlen oder ablaufdaten)
- Führung/Entscheidungen: nicht bewertet (noch keine kennzahlen oder ablaufdaten)

## Engpass (Ressource, RACE-C (Abschluss)) — bestätigt

Thomas Berger (Inhaber) (inhaber) zu 140% ausgelastet in RACE-C (Abschluss)

Konfidenz 0.95. Tests:
- relief: bestanden — +10% Kapazität bei inhaber: Durchsatz 2.88 -> 3.16 Einheiten/Woche
- starvation: bestanden — nach inhaber (140%): buero 32%, montage 45%, werkstatt 50% -> Kapazität wartet/leer
- queue: bestanden — Aufmaß: 46 in der Warteschlange, ~315 h Wartezeit; Ereignisprotokoll: Median 315 h Wartezeit vor 'aufmass' (p90 615 h, n=76)
- expedite: bestanden — 1 Aussage(n), z. B. "Berger: Das Aufmaß mache ich selbst, immer freitags und samstags"
- absence: bestanden — 1 Aussage(n), z. B. "Berger: Wenn ich im Urlaub bin, passiert beim Aufmaß gar nichts, dann stapeln sich die Anfragen."

**Voraussichtlich nächster Engpass:** Nach der Entlastung reicht die Kapazität: Der Markt (RACE) wird voraussichtlich zum Engpass (~18% Nachfrage-Spielraum). Schritt 1 neu durchführen.

### Weitere Kandidaten
- con-RACE-C-pol-f46364b94e (Kandidat, Regel, Konfidenz 0.45): Regel: Angebote werden gesammelt montags verschickt.

### Ungeklärte Signale
- Auftragsabwicklung: Signale in Auftragsabwicklung zeigen noch nicht auf eine Ressource, Regel oder den Markt

### Mess- und Erhebungsschritte
- Belegte Kennzahl für RACE-R (Reichweite) beschaffen: Besucher/Impressionen pro Woche, Werbebudget, Anzahl Werbemittel
- Belegte Kennzahl für RACE-E (Bestandskunden) beschaffen: Kündigungen, Wiederkauf-/Upsell-Quote, Kundenwert
- Belegte Kennzahl für Betrieb/Produktion beschaffen: Auslastung und Warteschlangen je Team/Maschine
- Belegte Kennzahl für Kundenservice beschaffen: Ticket-Rückstand, Zeit bis Erstantwort und Lösung
- Belegte Kennzahl für Finanzen beschaffen: Zeit bis Rechnung, Zahlungsziel (DSO), Monatsabschluss, Freigabe-Wartezeit
- Belegte Kennzahl für Personal beschaffen: Zeit bis Einstellung, offene Schlüsselstellen, Einarbeitungszeit
- Belegte Kennzahl für Einkauf beschaffen: Fehlbestände, Schwankung der Lieferzeiten
- Belegte Kennzahl für Produkt/Entwicklung beschaffen: Release-Warteschlange, Wartezeit auf Review/Test
- Belegte Kennzahl für IT/Daten beschaffen: Stunden manueller Datenübertragung, Schnittstellenfehler, Berichtsverzug
- Belegte Kennzahl für Recht/Compliance beschaffen: Länge und Wartezeit der Prüf-Warteschlange
- Belegte Kennzahl für Führung/Entscheidungen beschaffen: Entscheidungen, die auf Inhaber/Schlüsselperson warten, Freigabe-Wartezeit
