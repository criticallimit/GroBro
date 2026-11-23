# Entwurf: Growatt-Cloud-Verarbeitung vom lokalen MQTT-Empfang trennen

**Status:** experimenteller Entwicklungszweig `audit/cloud-forward-isolation`, noch nicht getestet und **nicht** nach `main` übernommen. Produktionsversion bleibt 3.3.43. Zu Issue #54.

## Gemeinsame Ursache

Bislang löst `grobro/grobro/client.py::__on_message` den synchronen Cloud-Connect aus, **bevor** das Gerätetelegramm in lokale Sensor-/Konfigurationsdaten verarbeitet wird. Langsamer DNS-/TLS-Aufbau hält deshalb den Source-Paho-Callback an.

## Prototyp

1. Die lokale MQTT-Eingangsverarbeitung übergibt optionale Cloud-Telegramme nur an `CloudForwardQueue`; sie ruft weder DNS noch TLS auf.
2. Der Cloud-Worker startet **erst bei tatsächlich aktivierter Cloud-Weiterleitung**. Bei Cloud aus entsteht kein zusätzlicher Netzwerk-Thread.
3. Es gibt **einen** Daemon-Worker und eine begrenzte FIFO-Warteschlange (höchstens 64 wartende Telegramme). **Kein pauschales Nachrichtenalter-Limit**: Der ursprüngliche Growatt-Cloud-Forwarder definiert keine TTL für erste Konfigurations-/Anmeldetelegramme.
4. Ist die Queue voll, werden neue Cloud-Telegramme verworfen und es erfolgt eine begrenzte Warnung. Nach einem Verbindungsfehler werden für dieselbe Device-ID 10 Sekunden lang keine erneuten Cloud-Verbindungsversuche gestartet. Keine unbeschränkte Warteschlange, kein Aufholen älterer Daten.
5. Der Worker benutzt weiterhin den bisherigen Cloud-MQTT-Client pro Gerät. Die Subscription auf `+/<Geräte-ID>` erfolgt jetzt bei **jedem erfolgreichen CONNACK**, damit sie bei einer neuen Session nach Reconnect wieder besteht. Dies ist eine gezielte Abweichung von der einmaligen initialen Subscription im Upstream.
6. `stop()` leert zunächst die Cloud-Queue; Cloud-Connect wird nicht mehr unter der gemeinsamen Shutdown-Sperre durchgeführt. Ein Cloud-DNS-/TLS-Aufruf kann als Daemon noch auslaufen, ohne die lokale Beendigung aufzuhalten.

## Offene Risiken vor Merge

- Bei langsamem Cloud-Connect kann ein bereits vom Worker übernommenes Telegramm verspätet an die Cloud gelangen. Das entspricht eher der bisherigen synchronen Weiterleitung als ein unbelegtes TTL-Verwerfen, kann jedoch nach Wiederherstellung zu verzögerten Messwerten führen. Überlauf und Shutdown bleiben explizite Verlustfälle.
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
- [ ] Neue Tests: Erstes Paket bleibt trotz langsamen Cloud-Connect erhalten; wiederholter Cloud-Connect-Fehler löst je Gerät nur einen Versuch im Cooldown aus.
- [ ] Bestehende echte MQTT-E2E-Suite einschließlich Cloud-Reconnect erfolgreich.
- [ ] Zwei Geräte über denselben Quellbroker; Cloud-Verbindung eines Geräts langsam, lokale HA-Telemetrie beider Geräte ohne Verzögerung.
- [ ] Zusätzliche CPU-, RAM- und Thread-Last unter Cloud aus / Cloud an messen.
- [ ] Erst dann Merge, vollständige Regression und neues Release nach Freigabe.


## Upstream-Kompatibilitätsabgleich (23.11.2026)

Der relevante Upstream-Quellpfad in `robertzaage/GroBro/grobro/grobro/client.py` gibt **jede erlaubte eingehende Growatt-Nachricht** mit unverändertem MQTT-Topic, Byte-Payload, QoS und Retain unmittelbar an den Cloud-Client weiter; die Cloud-Verbindung wird beim ersten Telegramm synchron erzeugt. Aus diesem Code ist **nicht ableitbar**, dass das erste Paket ein bestimmter Konfigurationstyp sein muss. Der Prototyp hatte anfangs eine unbelegte Fünf-Sekunden-Verfallsregel, die inzwischen wieder entfernt wurde. Das vermeidet gerade den möglichen Verlust initialer Protokollnachrichten aufgrund des Connect-Alters.

**Neuer Sicherungstest:** der Cloud-Queue-Pfad wahrt Byte-Inhalt, Topic, QoS/Retain und FIFO-Reihenfolge für mehrere Geräte. Der asynchrone Cloud-Worker erkennt jetzt auch `MQTT_ERR_NO_CONN` bzw. andere lokale Publish-Ablehnungen ohne Exception und aktiviert den gerätespezifischen Cooldown.

**Ungeklärt vor Merge:** tatsächliche Cloud-Anmeldung und erste Konfigurationsnachricht gegen einen echten Growatt-Cloud-Endpunkt validieren; die **Pufferüberlauf-/Shutdown-Politik** gegenüber dem Upstream als bewusste Verhaltensänderung prüfen. Der Test mit lokalem Mosquitto kann das Cloud-Anmeldeprotokoll nicht belegen. Bis dahin keine Produktivübernahme.

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

## Früher SUBACK / atomare MID-Registrierung (23.11.2026)

Der Empfang des Broker-SUBACK kann bei einem `subscribe()`-Aufruf vom Paho-Netzwerkthread parallel eintreffen. Ohne gemeinsame Sperre lag zwischen Rückgabe von `(rc, mid)` und dem Anlegen des MID-Watchdogs ein mögliches Race Window. Die Subscription wurde dann möglicherweise nie als bestätigt erkannt und unnötig erneut versucht.

**Branch-Korrektur:** Bei erstmaligem Cloud-CONNACK **und** beim Retry bleiben der `subscribe()`-Aufruf und die Registrierung des MIDs unter dem bereits vorhandenen `_cloud_subscription_lock` (RLock). Der `on_subscribe`-Callback benutzt dieselbe Sperre. Der Empfang kann deshalb nicht vor Abschluss der Registrierung ausgewertet werden. Nach der Freigabe wird der MID-geprüfte Callback regulär abgearbeitet.

**Regressionstest:** `test_cloud_suback_racing_subscribe_mid_registration_is_not_lost` startet aus dem simulierten Subscribe-Aufruf einen separaten Bestätigungs-Thread und weist nach, dass der passende SUBACK den Watchdog beendet, ohne einen falschen Retry zu planen. Ein direkt reentrant im gleichen Thread ausgeführter künstlicher `on_subscribe`-Aufruf gehört nicht zum regulären Paho-Callback-Modell; dieser Sonderfall ist nicht Gegenstand des Nachweises.

**Freigabe unverändert:** Keine vollständige pytest-Ausführung und keine echten Broker-/Growatt-Cloud-Tests. Die Fünf-Sekunden-Verfallsregel wurde entfernt; die Auswirkungen des begrenzten Puffers bei Cloud-Störungen bleiben zu testen. Kein Merge nach `main` und kein Release.

## Prüfung vorhandener E2E-Tests: keine Callback-Verfälschung (23.11.2026)

Die E2E-Prüfung des Cloud-Reconnects hatte bei der Erweiterung um den Rückkanal die produktiven Paho-Callbacks `forward.on_message` und `forward.on_subscribe` überschrieben. Dadurch wurden lediglich Mess-Ereignisse gesetzt; der tatsächliche Cloud→Gerät-Forwarding-Handler sowie die neue MID-/SUBACK-Verarbeitung wurden im Test umgangen. Das ist ein **Testdesign-Fehler**, keine belegte Störung im produktiven Code.

Im Branch werden beide Callbacks nur noch mit Beobachtern **umhüllt**: Erst wird der originale Handler aufgerufen, dann werden Beobachtungsereignisse gesetzt. Die SUBACK-Beobachtung prüft den Reason-Code über die vorhandene Helper-Funktion `subscription_rejected`. Damit bleibt der reale E2E-Test näher an der produktiven Pipeline. Der Test ist noch nicht ausgeführt; zunächst ist weiterhin ein echter Mosquitto-Testaufbau erforderlich.

## Protokollschutz für erste Telegramme (23.11.2026)

Die willkürlich eingeführte 5-Sekunden-TTL ist aus dem Prototyp entfernt ([Cloud-Dispatcher](../grobro/grobro/cloud_dispatch.py), [Cloud-Client](../grobro/grobro/client.py)). Ein Telegramm, das bereits zur Cloud-Weiterleitung akzeptiert wurde, wird daher nicht allein wegen einer langsamen Erstverbindung verworfen. Topic, Binär-Payload, QoS und Retain bleiben unverändert. Der vorhandene Test für den spät ausgeführten Cloud-Publish wurde auf **Erhaltung des ersten Konfigurationstelegramms** umgestellt.

Die Cloud-Warteschlange bleibt auf 64 *wartende* Elemente begrenzt; ein bereits laufender Versand zählt nicht dazu. Bei Überlauf werden neue Cloud-Telegramme abgelehnt, bei Shutdown wird der Rest verworfen. Das schützt lokale Verarbeitung und RAM, ist aber eine sichtbare Abweichung vom synchron blockierenden Upstream und muss bei echter Cloud-Störung gemessen werden.

## E2E-Cloud-Rückkanal: tatsächliche Broker-Zustellung (23.11.2026)

Bei der Prüfung des bisherigen Cloud-E2E-Tests zeigte sich, dass dessen Beobachtung auf `forward.on_message` allein nicht beweist, dass das Paket von `__on_message_forward_client` tatsächlich zum **Quellbroker** gelangt. Ohne ausdrücklich aktivierte Cloud-Policy kann der produktive Rückkanal den Empfang richtigerweise filtern und der bisherige Beobachter trotzdem grün werden.

**Teständerung im Branch:** `test_real_cloud_direct_forwarding_and_reconnect` setzt die Cloud-Policy ausdrücklich auf aktiv, benutzt ein durch den vorhandenen Growatt-Builder erzeugtes gültiges binäres Konfigurationslese-Telegramm und registriert einen separaten MQTT-Zeugen auf dem **Quellbroker** (Topic `s/33/<Device-ID>`). Geprüft wird die unveränderte Byte-Payload sowohl vor als auch nach Cloud-Reconnect. Der Cloud-Paho-`on_message`- und `on_subscribe`-Handler bleibt erhalten und wird nur zur Beobachtung umhüllt.

**Offen:** Dieser Test ist im Repository geändert, aber mangels `paho-mqtt` und Mosquitto noch nicht lokal ausführbar. Er ersetzt keine echte Growatt-Cloud-Anmeldung; die vorhandene Quell- und Cloud-Dummy-Verbindung verwendet lokale Broker und simuliert die notwendige Protokollkommunikation.

## Gesamtclient-Audit: SUBACK-vs-CONNACK-Sitzungswechsel (23.11.2026)

**Fehler:** Im bereits eingeführten `on_cloud_subscribe` wurde nur die MID-Prüfung unter dem Subscription-RLock durchgeführt. Für einen abgelehnten SUBACK wurde die Sperre anschließend gelöst und die **aktuelle** Sitzungskennung erneut eingelesen, bevor ein Retry geplant wurde. Ein dazwischen liegender neuer CONNACK konnte somit einen Retry für eine bereits neu gestartete Sitzung auslösen.

**Korrektur:** Die Validierung von `(Epoche, MID)`, das Löschen des alten SUBACK-Watchdogs und die Entscheidung über Subscription-Erfolg bzw. Retry laufen jetzt vollständig unter **demselben** RLock. Das hält den Zustand konsistent, bis der neue CONNACK seine Epoche registrieren kann.

**Regressionstest:** `test_cloud_suback_retry_cannot_cross_reconnect_epoch` startet einen echten parallelen Reconnect-Callback exakt während der simulierten SUBACK-Auswertung. Der Reconnect muss bis zum abgeschlossenen alten Zustandsübergang warten und danach alle alten Retry-Timer löschen. Test noch nicht ausgeführt.

**Testumgebung:** `pytest` und `pydantic` sind vorhanden, `paho-mqtt`, `crc` und `mosquitto` fehlen. Die vollständige Suite bzw. echte MQTT-E2E-Tests können damit hier nicht ausgeführt werden; isolierte Cloud-Queue-Tests sind nicht gleichwertig mit Cloud-Client-Tests.

## Noch nicht freigegeben: Reihenfolge erstes Cloud-SUBSCRIBE / erstes Geräte-PUBLISH (23.11.2026)

**Neu identifiziertes Kompatibilitätsrisiko:** Das ursprüngliche GroBro ruft bei einer neuen Cloud-Verbindung nach synchronem `connect()` zuerst `subscribe(f"+/{device_id}")` auf, startet dann `loop_start()` und übergibt erst anschließend das erste Geräte-Paket an `publish()`. Im isolierten Entwicklungszweig wird das Abo dagegen erst im asynchronen Paho-`on_connect` eingerichtet; `__connect_to_growatt_server` kann nach `loop_start()` zurückkehren, bevor dieser Callback tatsächlich gelaufen ist. Das erste Cloud-PUBLISH könnte dadurch vor dem SUBSCRIBE in die MQTT-Ausgangswarteschlange gelangen.

**Bewertung:** Diese Umordnung ist eine Protokolländerung und aktuell nicht durch vollständige Paho-/Broker-Tests gedeckt. Eine bloße Prüfung, dass später sowohl PUBLISH als auch SUBACK eintreffen, belegt die entscheidende ursprüngliche Reihenfolge nicht.

**Freigabebedingung:** Vor Merge muss der Startpfad nachweislich `SUBSCRIBE queued before first PUBLISH` herstellen und zugleich die bereits ergänzte Subscription-Erneuerung auf jedem Reconnect erhalten. Die Lösung darf den lokalen Source-MQTT-Callback nicht blockieren und soll unnötige doppelte erste Subscriptions vermeiden. Dazu ein gezielter Paho-E2E-Test mit verzögertem CONNACK; die vorhandenen Mocktests müssen dazu konsistent angepasst werden. Der produktive Cloud-Worker wartet jetzt auf die lokal eingereihte Cloud-Subscription; die reale Broker-Validierung bleibt offen.

**Unabhängig verifizierbar:** Die bereits lokal vorhandene exakte Dispatcher-Version mit Git-Blob-Hash `398903c69317b29feea055436a84e6ea5aaccd20` wurde erneut isoliert getestet: `5 passed in 0.10s`. Das ist keine Cloud-Client-/Paho-Validierung.

## Reihenfolge erstes Cloud-SUBSCRIBE vor erstem PUBLISH (23.11.2026)

Der separate Cloud-Worker wartet nun ereignisgesteuert mit einer Condition auf eine erfolgreich lokal eingereihte Cloud-Antwort-Subscription. Erst wenn der CONNACK-Handler SUBSCRIBE eingereiht und die MID-Überwachung registriert hat, darf der Worker PUBLISH aufrufen. Der lokale Growatt-Source-Callback wartet weiterhin nicht auf Cloud. Das ist eine lokale Queue-Reihenfolge, keine Garantie für den Broker-SUBACK.

Ein Cloud-Disconnect setzt die Freigabe zurück. Ein neuer erfolgreicher CONNACK und SUBSCRIBE gibt sie erneut frei. Ein abgelehntes SUBSCRIBE löst den bereits vorhandenen Subscription-Retry aus; Shutdown weckt wartende Worker, die danach keine Nachrichten mehr veröffentlichen dürfen.

Drei neue Regressionstests für initiales SUBSCRIBE-before-PUBLISH, erneuten Reconnect und Shutdown-Wakeup sind hinzugefügt. Der bestehende reale MQTT-E2E-Test wurde auf den zeitgestempelten Worker-Pfad umgestellt. Die neuen Tests sind hier wegen fehlender Paho-, CRC- und Mosquitto-Abhängigkeiten noch nicht ausgeführt.

Offenes Betriebsrisiko: Wenn eine erfolgreiche Cloud-Verbindung ausbleibt, wartet der Cloud-Worker unbeschränkt. Weitere Nachrichten werden bis zum festen Limit von 64 wartenden Paketen aufgenommen, danach verworfen; die lokale HA-Verarbeitung bleibt frei. Vor Merge echte längere Offline-Phasen und Broker-Reconnect prüfen.

## Längerer Cloud-Ausfall: Diagnose und atomarer Shutdown (23.11.2026)

Das erste angenommene Growatt-Telegramm bleibt erhalten, auch wenn ein CONNACK bzw. eine lokal akzeptierte Cloud-Subscription länger ausbleibt. Ausschließlich der separate Cloud-Worker wartet auf die Condition. Ein diagnostischer Wakeup alle 30 Sekunden protokolliert dann eine Warnung; er löst selbst keine Netzwerkabfrage aus und verwirft keine Telegramme.

Zwei Regressionstests mit auf 50 ms verkürztem Diagnoseintervall überprüfen die Wiederaufnahme des ersten Pakets nach späterem CONNACK und den Shutdown ohne nachfolgenden Publish. Die vollständige Client-Suite ist in dieser Umgebung noch nicht ausführbar.

Shutdown-Race erkannt und korrigiert: Bisher wurden Subscription-Timer gelöscht und erst danach das Stop-Flag gesetzt. Ein Paho-Callback konnte dazwischen erneut einen Timer registrieren. Nun wird _forward_stopped=True vor der Timer-Bereinigung im selben Condition-RLock gesetzt und wartende Worker sofort benachrichtigt.

Verbleibende Grenze: Wenn Cloud nie wieder einen erfolgreichen CONNACK liefert, bleibt der Worker absichtlich wartend und die Warteschlange kann nach 64 weiteren Paketen überlaufen. Die Warnung diagnostiziert, behebt aber keine vollständige Transportstörung. Reale Paho/Mosquitto-Tests und Growatt-Cloud-Kompatibilität bleiben offen.

## Geräteübergreifendes Head-of-Line-Blocking: neuer Freigabeblocker (23.11.2026)

Die aktuelle CloudForwardQueue betreibt genau einen Daemon-Worker. Dieser ruft den Client-Forwarder synchron auf. Seit der Absicherung 'erst SUBSCRIBE, dann erstes PUBLISH' kann der Client auf einen ausbleibenden Cloud-CONNACK eines Gerätes unbegrenzt warten. Der Worker ist damit vollständig belegt. Selbst wenn ein zweites Gerät eine funktionierende Cloud-Verbindung hat, wird dessen Paket in der globalen FIFO nicht mehr bearbeitet. Dieses Problem ist eine direkte Folge des Codepfads, nicht bloß eine unbewiesene Growatt-Vermutung.

Ein neuer Test 'test_cloud_stalled_device_does_not_block_other_device' reproduziert diese Geräte-Konkurrenz mit zwei Events. Er ist ausdrücklich als pytest.xfail(strict=True) markiert, solange die Isolierung nicht implementiert ist; ein versehentliches XPASS wird bei strict=True als Fehler behandelt. Test ist im GitHub-Zweig angelegt, aber in dieser Runde nicht ausgeführt.

Ein möglicher Architekturweg ist ein begrenzter gerätespezifischer Worker-Pool oder eine nichtblockierende Wiederanmeldung mit fairer Geräteplanung. Die Abnahme muss dabei pro Gerät FIFO, binäre Payload/QoS/Retain, eine **globale** Speicher-/Queue-Grenze, Shutdown und späteren Reconnect nachweisen. Erst danach sollte die Ein-Worker-Architektur ersetzt werden. Die bestehende Version ist keine freigabefähige Mehrgeräte-Lösung.
