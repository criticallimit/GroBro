# Entwurf: Growatt-Cloud-Verarbeitung vom lokalen MQTT-Empfang trennen

**Status:** experimenteller Entwicklungszweig `audit/cloud-forward-isolation`, noch nicht getestet und **nicht** nach `main` übernommen. Produktionsversion bleibt 3.3.43. Zu Issue #54.

## Gemeinsame Ursache

Bislang löst `grobro/grobro/client.py::__on_message` den synchronen Cloud-Connect aus, **bevor** das Gerätetelegramm in lokale Sensor-/Konfigurationsdaten verarbeitet wird. Langsamer DNS-/TLS-Aufbau hält deshalb den Source-Paho-Callback an.

## Prototyp

1. Die lokale MQTT-Eingangsverarbeitung übergibt optionale Cloud-Telegramme nur an `CloudForwardQueue`; sie ruft weder DNS noch TLS auf.
2. Der Cloud-Worker startet **erst bei tatsächlich aktivierter Cloud-Weiterleitung**. Bei Cloud aus entsteht kein zusätzlicher Netzwerk-Thread.
3. Es gibt **einen** Daemon-Worker, eine begrenzte FIFO-Warteschlange (höchstens 64 noch nicht bearbeitete Telegramme) und ein Zeitlimit von 5 Sekunden. Die Frische wird sowohl vor dem Aufruf als auch unmittelbar vor dem Cloud-Publish nach ggf. langsamem Connect geprüft.
4. Ist die Queue voll, werden neue Cloud-Telegramme verworfen und es erfolgt eine begrenzte Warnung. Nach einem Verbindungsfehler werden für dieselbe Device-ID 10 Sekunden lang keine erneuten Cloud-Verbindungsversuche gestartet. Keine unbeschränkte Warteschlange, kein Aufholen älterer Daten.
5. Der Worker benutzt weiterhin den bisherigen per-Gerät-Cloud-Client und die originale `connect -> subscribe -> loop_start`-Reihenfolge.
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
