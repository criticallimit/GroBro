# Better GroBro 3.3.4 — Differences from robertzaage/GroBro

## User-relevant differences

- Aktueller Batterieenergieinhalt wird in der Better-GroBro-Übersicht und als vorgeschlagene Home-Assistant-Anzeigegenauigkeit mit zwei Nachkommastellen dargestellt; die interne Berechnung bleibt unverändert.

---

# Better GroBro 3.3.3 — Differences from robertzaage/GroBro

## User-relevant differences

- Home-Assistant-Entitäten werden bei einer MQTT-Discovery-Aktualisierung nicht mehr durch eine leere Konfiguration zwischenzeitlich gelöscht.
- Gespeicherte Batterieanzahl wird vor dem ersten Telemetriepaket berücksichtigt, damit Bat2/Bat3 nach Neustarts erhalten bleiben.
- Die zusätzliche Übersicht „NOAH – PV- und Batteriezustand“ entfällt; der aktuelle kWh-Energieinhalt erscheint als Batteriekachel mit identischem Batteriesymbol neben den einzelnen Akkus.\n- Regressionstests für Discovery-Aktualisierungen, persistierte Batterie-Slots und die neue Ingress-Anordnung.

---

# Better GroBro 3.3.2 — Differences from robertzaage/GroBro

## User-relevant differences

- Der in 3.3.1 hinzugefügte Sensor für nominelle Batteriekapazität wird durch den Sensor „Current Battery Energy“ (kWh) ersetzt. Dieser berechnet die aktuell gespeicherte Energie näherungsweise anhand von gemeldeter Akkuanzahl und aktuellem Gesamt-SoC.
- Bei fehlender oder ungültiger Live-Messung wird kein geschätzter Wert erfunden. Es handelt sich weder um die Nennkapazität noch einen Energiezähler.
- Kein zusätzlicher Nennkapazitätssensor.

---

# Better GroBro 3.3.1 — Differences from robertzaage/GroBro

## User-relevant differences

- Neuer Sensor „Total Battery Capacity“ (kWh) für NOAH 2000 und NEXA 2000, nur bei plausibler vom Gerät gemeldeter Modulanzahl (2,048 kWh je Modul).
- Ingress zeigt die Gesamtkapazität und das Alter zwischengespeicherter Batteriewerte an. Home-Assistant-Batteriesensoren erhalten Aktualitätsattribute.
- Holding-Register-Antworten und NEO-Schreibbestätigungen verbessert; 100%-Leistungslimit korrekt normalisiert.
- Asynchronen Ingress-Test stabilisiert und Regressionstests erweitert.

---

# Better GroBro 3.3.0 — Differences from robertzaage/GroBro

- NOAH: PV1-/PV2- und Systemtemperatur sowie Batterie-SoH als zusätzliche Sensoren und in der Ingress-Übersicht.
- Persistente Batteriezustandswerte bis zu zwölf Stunden; Live-Leistung und Energiezähler werden nicht aus dem Cache wiederhergestellt.
- Die automatisch erkannte Batterieanzahl bleibt bei kurzzeitigen Verbindungsabbrüchen erhalten; vorhandene manuelle Zuordnungen haben Vorrang.
- MQTT-Testinfrastruktur repariert; automatisierte Tests für Python 3.11, 3.12 und 3.13 erfolgreich.

Hinweis: Die Umstellung der NOAH-Ladeleistung auf Register 412 ist nicht Bestandteil dieses Releases und erfordert einen Gerätetest.

---

# Better GroBro 3.2.3 — Differences from robertzaage/GroBro

## User-relevant differences

- Growatt Cloud forwarding again follows Robert Zaage's GroBro: synchronous connection setup and direct MQTT forwarding, without Better GroBro's own backlog or replay after an outage.

- Better GroBro now includes a redesigned user interface.
