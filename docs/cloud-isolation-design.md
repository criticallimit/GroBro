# Entwurf: Growatt-Cloud-Verarbeitung vom lokalen MQTT-Empfang trennen

**Status:** experimenteller Entwicklungszweig `audit/cloud-forward-isolation`, noch nicht getestet und **nicht** nach `main` übernommen. Produktionsversion bleibt 3.3.43. Zu Issue #54.

## Gemeinsame Ursache

Bislang löst `grobro/grobro/client.py::__on_message` den synchronen Cloud-Connect aus, **bevor** das Gerätetelegramm in lokale Sensor-/Konfigurationsdaten verarbeitet wird. Langsamer DNS-/TLS-Aufbau hält deshalb den Source-Paho-Callback an.

## Prototyp

1. Die lokale MQTT-Eingangsverarbeitung übergibt optionale Cloud-Telegramme nur an `CloudForwardQueue`; sie ruft weder DNS noch TLS auf.
2. Der Cloud-Worker startet **erst bei tatsächlich aktivierter Cloud-Weiterleitung**. Bei Cloud aus entsteht kein zusätzlicher Netzwerk-Thread.
3. Es gibt **einen** Daemon-Worker, eine begrenzte FIFO-Warteschlange (höchstens 64 noch nicht bearbeitete Telegramme) und ein Zeitlimit von 5 Sekunden. Die Frische wird sowohl vor dem Aufruf als auch unmittelbar vor dem Cloud-Publish nach ggf. langsamem Connect geprüft.
4. Ist die Queue voll, werden neue Cloud-Telegramme verworfen und es erfolgt eine begrenzte Warnung. Nach einem Verbindungsfehler werden für dieselbe Device-ID 10 Sekunden lang keine erneuten Cloud-Verbindungsversuche gestartet. Keine unbeschränkte Warteschlange, kein Aufholen älterer Daten.
5. Der Worker benutzt weiterhin den bisherigen Cloud-MQTT-Client pro Gerät. Die Subscription auf `+/<Geräte-ID>` erfolgt jetzt bei **jedem erfolgreichen CONNACK**, damit sie bei einer neuen Session nach Reconnect wieder besteht. Dies ist eine gezielte Abweichung von der einmaligen initialen Subscription im Upstream.
6. `stop()` leert zunächst die Cloud-Queue; Cloud-Connect wird nicht mehr unter der gemeinsamen Shutdown-Sperre durchgeführt. Ein Cloud-DNS-/TLS-Aufruf kann als Daemon noch auslaufen, ohne die lokale Beendigung aufzuhalten.

## Offene Risiken vor Merge

- Der **erste** bereits vom Worker übernommene Telegrammversand kann nach einem langsamen, synchronen `connect()` noch verzögert stattfinden. Das Queue-Alterslimit prüft derzeit nur **vor** diesem Aufruf. Für eine strikte Frischegarantie wäre eine weitere Prüfung unmittelbar vor `publish()` erforderlich.
- Ein einzelner Worker bewahrt FIFO über alle Geräte, blockiert aber Cloud-Verarbeitung anderer Geräte, wenn die Cloud-Verbindung eines Geräts hängt. Die lokale MQTT-Verarbeitung ist davon isoliert. Mehr Worker wären nur mit begrenzter und nachweisbar korrekt geordneter Nebenläufigkeit sinnvoll.
- Bei Überlauf/Shutdown werden **Cloud-Telegramme** verworfen, keine lokalen HA-Telegramme. Das ist eine beabsichtigte Abwägung gegen Rückstau.
- TLS-Zertifikatsverhalten bleibt zunächst exakt wie vorher; Sicherheitsmigration separat testen.
- Lokale Publish-Annahme vs. Brokerzustellung bleibt als **zweites, unabhängiges** systemweites Arbeitspaket offen.
- Die bisherigen Upstream-Forwarding-Tests setzen synchrone Aufrufe voraus; die Callback-Tests wurden auf asynchronen Versand umgestellt, müssen aber tatsächlich ausgeführt werden.
- Ein initialer 10-Sekunden-Cooldown je Gerät verhindert unmittelbare erneute Versuche nach Ausnahmen. Verhalten bei Paho-\`publish()\`-Rückgabecodes (ohne Ausnahme), bei laufendem Paho-Cloud-Reconnect und bei mehreren gleichzeitig betroffenen Geräten bleibt separat zu prüfen.

## Abnahme vor Merge

- [ ] Alle vorhandenen `tests/test_grobro_client.py`-Tests (inklusive Cloud-Reihenfolge/Shutdown) erfolgreich.
- [ ] Neuer Test: blockierte Cloud verhindert **nicht** lokale Verarbeitung eines gültigen Gerätetelegramms.
- [ ] Neuer Test: Cloud-Queue begrenzt und leert Rückstau bei Stop.
- [ ] Neuer Test: Shutdown wartet nicht auf blockierenden Cloud-Connect.
- [ ] Neue Tests: Paket während Cloud-Connect veraltet; wiederholter Cloud-Connect-Fehler löst je Gerät nur einen Versuch im Cooldown aus.
- [ ] Bestehende echte MQTT-E2E-Suite einschließlich Cloud-Reconnect erfolgreich.
- [ ] Zwei Geräte über denselben Quellbroker; Cloud-Verbindung eines Geräts langsam, lokale HA-Telemetrie beider Geräte ohne Verzögerung.
- [ ] Zusätzliche CPU-, RAM- und Thread-Last unter Cloud aus / Cloud an messen.
- [ ] Erst dann Merge, vollständige Regression und neues Release nach Freigabe.


## Upstream-Kompatibilitätsabgleich (23.11.2026)

Der relevante Upstream-Quellpfad in `robertzaage/GroBro/grobro/grobro/client.py` gibt **jede erlaubte eingehende Growatt-Nachricht** mit unverändertem MQTT-Topic, Byte-Payload, QoS und Retain unmittelbar an den Cloud-Client weiter; die Cloud-Verbindung wird beim ersten Telegramm synchron erzeugt. Aus diesem Code ist **nicht ableitbar**, dass das erste Paket ein bestimmter Konfigurationstyp sein muss. Folglich kann derzeit weder bestätigt noch ausgeschlossen werden, dass die 5-Sekunden-Verfallsregel initiale für die Cloud wichtige Nachrichten verwirft.

**Neuer Sicherungstest:** der Cloud-Queue-Pfad wahrt Byte-Inhalt, Topic, QoS/Retain und FIFO-Reihenfolge für mehrere Geräte. Der asynchrone Cloud-Worker erkennt jetzt auch `MQTT_ERR_NO_CONN` bzw. andere lokale Publish-Ablehnungen ohne Exception und aktiviert den gerätespezifischen Cooldown.

**Ungeklärt vor Merge:** tatsächliche Cloud-Anmeldung und erste Konfigurationsnachricht gegen einen echten Growatt-Cloud-Endpunkt validieren; die neue Verfalls-/Überlaufpolitik gegenüber dem Upstream als bewusste Verhaltensänderung freigeben oder so anpassen, dass initiale protokollwichtige Telegramme nicht verloren gehen. Der Test mit lokalem Mosquitto kann das Cloud-Anmeldeprotokoll nicht belegen. Bis dahin keine Produktivübernahme.

## Cloud-Rückkanal nach Reconnect (neuer Befund)

Der ursprüngliche Code abonnierte `+/<Geräte-ID>` nur während `__connect_to_growatt_server`. Bei einem Reconnect mit neuer/sauberer MQTT-Session kann dieses Subscription verloren sein, auch wenn das erneute Cloud-Publish weiterhin funktioniert. Im Branch liegt das Subscribe nun im `on_connect`-Callback des Cloud-Paho-Clients und wird auf jedem erfolgreichen CONNACK wiederholt. Abgelehnte Verbindungen oder ein bereits gestoppter Client abonnieren nichts.

- **Unit-Test:** aufeinanderfolgende erfolgreiche Cloud-CONNACKs erzeugen erneute Subscription; abgelehnter CONNACK und Shutdown nicht.
- **Real-MQTT-Test:** `tests/test_mqtt_e2e.py::test_real_cloud_direct_forwarding_and_reconnect` prüft jetzt zusätzlich Empfang auf dem Cloud-Rückantwort-Topic unmittelbar vor und nach dem Reconnect; nach Reconnect wird explizit auf SUBACK gewartet.
- **SUBACK-Härtung:** Der Cloud-Client prüft einen abgelehnten SUBACK jetzt im `on_subscribe`-Callback und meldet ihn als Fehler; eine lokale Subscribe-Ausnahme wird im `on_connect`-Callback abgefangen. Das meldet fehlenden Zugriff, stellt ihn aber ohne neue erfolgreiche Verbindung noch nicht wieder her. Es existiert kein separater vollständiger Cloud-Ready-Status für die Ingress-Oberfläche.

## Zusätzliche Rückkanal-Abnahmen

- [ ] Broker akzeptiert Subscription: kein Fehlalarm im SUBACK-Callback.
- [ ] Broker lehnt Subscription per SUBACK ab: eindeutiger Logfehler für das betroffene Gerät; nicht als freigegeben interpretieren.
- [ ] Lokaler Subscribe-Aufruf wirft einen Transportfehler: Paho-Netzwerk-Callback bleibt ohne unkontrollierte Exception.
- [ ] Verspäteter SUBACK nach Add-on-Shutdown: wird ignoriert.
- [ ] Recovery nach abgelehntem SUBACK: **auf Entwicklungszweig implementiert, noch ungetestet**. Ein verzögerter Einmal-Timer pro betroffenem Gerät; 10, 20, 40, 80, 160, höchstens 300 Sekunden. Kein zusätzlicher MQTT-Connect oder permanenter Polling-Loop. Erfolgreicher SUBACK bzw. neuer CONNACK hebt alte Retry-Timer auf; Shutdown verwirft sie.

## Gezielter SUBACK-Retry (Entwicklungszweig)

- Fehlerquelle: Broker lehnt `SUBSCRIBE` im SUBACK ab, lokaler `subscribe()` wirft oder meldet eine Fehlerrückgabe.
- Reaktion: **ein** verzögerter Timer je betroffener Geräte-Cloud-Verbindung. Exponentieller Backoff 10–300 Sekunden. Timer ist daemonisiert, führt nur `subscribe()` auf der bestehenden MQTT-Verbindung aus und ruft nie direkt `connect()` auf.
- Kein Retries bei erfolgreicher Subscription; erfolgreicher SUBACK löscht den Timer und setzt Backoff zurück.
- Neuer CONNACK inkrementiert eine Sitzungskennung, löscht alle alten Timer des Geräts und startet das reguläre Abo; ein veralteter Timer führt wegen Sitzungsvergleich keine Aktion aus.
- Beim Beenden werden alle Timer abgebrochen und die Statusdaten geleert.
- **Ergänzt im Entwicklungszweig:** Bei lokal akzeptierter Subscription mit gültiger MQTT-MID wird eine **8-Sekunden-SUBACK-Frist** verfolgt. Ein Timeout plant einen gedrosselten Neuversuch ein. Bei dauerhaft vom Broker verweigerter Subscription laufen bis zu einem Timer alle fünf Minuten pro betroffenem Gerät weiter. Ein eigener Cloud-Status in Ingress ist noch nicht implementiert.
- **Nachweis:** Regressionstests mit Fake-Timer angelegt, nicht ausgeführt. Echte Paho/Broker-Tests stehen aus.

## MID-gebundener SUBACK-Timeout (23.11.2026)

- Für einen angenommenen `subscribe()`-Aufruf mit gültiger Paho-MID wird **ein achtsekündiger Watchdog** angelegt. Der zugehörige Zustandswert enthält `(Verbindungs-Epoche, MID)`.
- Nur ein `on_subscribe` mit passender aktueller MID darf den Watchdog löschen oder die Subscription als erfolgreich behandeln. Ein verspäteter SUBACK für einen abgelaufenen Versuch wird ignoriert.
- Fehlt SUBACK, wird der Watchdog gelöscht und der vorhandene **10–300-Sekunden-Backoff** für einen neuen Subscribe-Versuch verwendet; keine permanente Abfrage oder neue MQTT-Verbindung.
- Bei CONNACK, erfolgreichem SUBACK und Shutdown werden unpassende Timer gelöscht. Timer-Callbacks kontrollieren zusätzlich die Identität des aktuell registrierten Timers, damit ein bereits storniertes Callback nicht nachträglich einen neueren Zustand verändert.
- **Offene Grenze:** Für nicht identifizierbare `subscribe()`-Rückgaben ohne ganzzahlige MID kann kein verlässlicher MID-gebundener Timeout aufgebaut werden. Die Produktionsbibliothek Paho liefert auf dem regulären Pfad `(result, mid)`; die Mock-Tests müssen konkrete MIDs liefern.
- **Weiter zu prüfen:** Paho-Callback-Timing, insbesondere ein SUBACK, der vor der Registrierung des MID-Watchdogs eintrifft, sowie ein MID-Wraparound; reale Zwei-Broker-Tests wurden noch nicht ausgeführt.
