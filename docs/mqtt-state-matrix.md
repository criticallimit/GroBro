# MQTT-Ende-zu-Ende-Abnahmematrix (Issue #54)

Stand: Better GroBro 3.3.43, 23.11.2026. Dieses Dokument beschreibt geplante Abnahmen, keine bestandenen Broker- oder Gerätetests.

## Abgrenzung
- Quellbroker: Growatt-Geräteverkehr (in der Add-on-Standardkonfiguration Port 7006).
- Zielbroker: Home Assistant MQTT (Standard Port 1883).
- Cloud: optionale, separate Verbindung zu Growatt.
- Gerätetypen in der Testmatrix: NOAH, NEO, NEXA, einschließlich mindestens zwei gleichzeitiger Geräte.
- Kommunikationsverfügbarkeit ist unabhängig vom NEO-Wechselrichter-Leistungszustand. Keine zeitbasierte Geräteabschaltung annehmen.
- Paho `publish().rc == 0` belegt nur Annahme in die lokale Queue, nicht Empfang oder Verarbeitung beim Broker.

## Zustandsmatrix
| Fall | Quelle | HA Ziel | Cloud | Erwartete Abnahme |
| --- | --- | --- | --- | --- |
| 01 | getrennt | getrennt | aus | Kein fälschliches Geräte-Online, keine Konfig-Reads |
| 02 | CONNACK, SUBACK offen | verbunden | aus | Keine Reads bis gültiger Source-SUBACK |
| 03 | SUBACK abgelehnt | verbunden | aus | Reads gesperrt, spätere Wiederherstellung nachvollziehbar |
| 04 | verbunden und subscribed | getrennt | aus | Eingangsverarbeitung darf weiterlaufen, keine Online-Behauptung für HA |
| 05 | verbunden | CONNACK abgelehnt | aus | HA-Daten bleiben offline, kein Online-Publish |
| 06 | verbunden | SUBACK offen/abgelehnt | aus | Steuerung nicht als bestätigt darstellen, Retry eindeutig |
| 07 | verbunden | verbunden, SUBACK bestätigt | aus | Telemetrie, Discovery, Steuerbefehle, Availability konsistent |
| 08 | Quellbroker reconnect | verbunden | aus | Source-Subscription neu, Reads erst nach SUBACK; kein veralteter Publikationscache |
| 09 | verbunden | Zielbroker reconnect | aus | LWT/Availability, Discovery und Messwerte geordnet neu aufgebaut |
| 10 | verbunden | HA Core Birth ohne MQTT reconnect | aus | Command Subscription und Discovery neu herstellen |
| 11 | beide reconnect | beide reconnect | aus | Reihenfolgeunabhängig, keine verlorenen Zustandsübergänge |
| 12 | verbunden | verbunden | langsam/unerreichbar | Lokaler Datenfluss darf nicht durch Cloud-Connect dauerhaft blockieren |
| 13 | verbunden | verbunden | verbunden | Cloud-Weiterleitung bewahrt Topic, Payload, QoS/Retain und Reihenfolge |
| 14 | verbunden | Publish lokal angenommen, dann Disconnect | aus | Keine behauptete Broker-Zustellung; Wiederherstellung und Cache-Replay prüfen |
| 15 | verbunden | verbunden | aus | Zwei Geräte gleichzeitig; Status/Cache/Kommandos bleiben isoliert |

## Mess- und Prüfpunkte
1. Für jede Verbindung separat: CONNECT/CONNACK, SUBSCRIBE/SUBACK, DISCONNECT, Reconnect, Rückgabecodes und zeitliche Reihenfolge.
2. Für jede Nachricht: Quelle, Empfangszeit, Device-ID, Topic, QoS/Retain, Parser-Ergebnis, Datenweitergabe an HA, erwartete Aktualisierung.
3. Für Verfügbarkeit: letzter tatsächlicher Geräteeingang, gesetzter Timeout, HA-Status, Ingress-Status, MQTT-Publish-Akzeptanz versus bestätigte Zustellung.
4. Für Steuerbefehle: Befehl empfangen, Geräte-MQTT bereit, Senden akzeptiert, Antwort empfangen, finaler Zustand.
5. Für Restart: Cache-Invaliderung, Discovery, Firmware, Batterie-Zuordnung, Smart-Meter und keine alten Leistungswerte als Live-Werte.
6. Für Cloud: bei Nichterreichbarkeit lokale Daten-Latenz messen und eventuelle Verarbeitungspausen nachweisen.

## Testebenen / Status
- **Codeprüfung:** zentrale Callback-Pfade und aktuelle Cache-Semantik angesehen.
- **Mock-Tests:** `tests/test_mqtt_state_matrix.py` ergänzt; noch nicht ausgeführt.
- **Lokaler Broker-Integrationstest:** offen (zwei simulierte Broker plus Nachrichtengenerator).
- **Home Assistant Praxis:** offen.
- **Echte Geräte:** offen.

## Release-Gate
Keine neue Versionsnummer nur aufgrund der Architekturaufnahme. Erst nach vollständiger Fehler-Reproduktion, dokumentierter Ursache, systemweiter Korrektur, erfolgreichen lokalen Tests und gesondert ausgewiesener Home-Assistant-Praxisprüfung versionieren.
