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
