# Better GroBro 3.3.10 — Differences from robertzaage/GroBro

## User-relevant differences

- When NEO firmware does not answer a standalone Wi-Fi signal-strength read (register 76), the config read queue continues after 10 seconds instead of waiting 60 seconds.
- The existing handling of genuine NEO Wi-Fi values in standalone or compound config responses is preserved; no signal value is fabricated.
- NOAH, NEXA and all other register read timeouts remain unchanged.
- Added a regression test for the targeted timeout.

---

# Better GroBro 3.3.9 — Differences from robertzaage/GroBro

## User-relevant differences

- Fixed the confirmed internal-key/display-label mismatch that prevented automatic config readback after changing Update Interval (NOAH, NEO, NEXA) or Time Zone (NEXA).
- Audited all config and holding command mappings across NOAH, NEO and NEXA; other command families do not share this mismatched-name check.
- No optimistic setting value is shown: the UI still waits for the actual device response.
- Added regression coverage of real register definitions.

---

# Better GroBro 3.3.8 — Differences from robertzaage/GroBro

## User-relevant differences

- Added a download button to the Better GroBro ingress Protokoll tab. It saves current-session Supervisor log entries as a timestamped UTF-8 text file without changing the existing log collection or retention.
- The export refuses to save a placeholder when the current session log has not yet become available.

---

# Better GroBro 3.3.7 — Differences from robertzaage/GroBro

## User-relevant differences

- NOAH, NEO and NEXA: after an accepted update-interval command, request the actual device setting automatically, without requiring the optional Growatt write acknowledgement or clicking Read All.
- NEXA time-zone changes use the same readback approach.
- Coalesce repeated changes to the same device setting and cancel pending readbacks on shutdown.
- Do not mirror requested values or change MQTT network configuration, restart or time commands.

---

# Better GroBro 3.3.6 — Differences from robertzaage/GroBro

## User-relevant differences

- After an acknowledged local configuration change, automatically read back the device's actual value for update interval (NOAH, NEO, NEXA) and NEXA time zone.
- Do not trigger immediate readback for MQTT connection settings, device restart or system time; preserve existing behavior for other controls.
- No optimistic Home Assistant state is published for these configuration changes.

---

# Better GroBro 3.3.5 — Differences from robertzaage/GroBro

## User-relevant differences

- Home Assistant MQTT command subscriptions are retried on subsequent device activity when the broker rejects a SUBACK, even when the initial subscribe call succeeded locally.
- NEXA PV1–PV4 and system temperature decoding corrected to use 0.1 K scale with Celsius offset, based on documented upstream raw telegrams.
- Added NEXA battery 2 temperature (register 42), supported by an observed raw telegram. Unverified battery 3/4 temperature registers remain untouched.
- No blanket one-decimal temperature display override for NOAH or NEO; that unverified change was reverted.
- Existing settings, entity identifiers, Growatt Cloud forwarding, and MQTT broker configuration are preserved.

---

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
