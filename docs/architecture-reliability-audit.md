# Better GroBro – systemweites Zuverlässigkeitsaudit

Stand: 2026-11-23 · Produktionsversion 3.3.43 · zentrale Planung: Issue #54.

## Architekturgrenzen

`grobro/ha_bridge.py` startet und verdrahtet zwei unabhängige Paho-Clients:
- **Growatt-Quelle**: `grobro/grobro/client.py` empfängt `c/#`, interpretiert Gerätetelegramme, verarbeitet Gateway/Cloud-Funktionen und sendet Steuer-/Registerbefehle auf `s/33/...`.
- **Home-Assistant-Ziel**: `grobro/ha/client.py` veröffentlicht Discovery, Telemetrie, Konfigurations- und Availability-Daten und nimmt HA-Kommandos entgegen.
- **Optionale Cloud**: in der Quelle pro Device-ID angelegte zusätzliche Paho-Verbindungen.
- **Ingress**: `grobro/ha/battery_ingress.py`, Supervisor-Konfiguration und Zustandsinventar ohne separaten Geräte-Pollingpfad.
- **Datenhaltung**: Laufzeit-/Publikations-Caches und ein davon getrenntes persistiertes Sensor-/Geräte-Metadatenmodell.

## Befunde und ursächliche Risiken

### P1 – Cloud-Verbindung blockiert Quell-Nachrichten-Callback

**Belegt durch Codepfad:** `Client.__on_message` in `grobro/grobro/client.py` ruft `__publish_to_growatt_server` vor `parser.unscramble` und den HA-Callbacks auf. Für ein neues Cloud-Gerät führt `__connect_to_growatt_server` innerhalb des Quell-Paho-Callbacks `client.connect(...)` synchron aus, geschützt durch `_forward_lifecycle_lock`.

**Auswirkung (Risiko, nicht gemessen):** DNS, TLS oder ein langsamer Cloud-Host kann die Verarbeitung eingehender **lokaler** NOAH-/NEO-/NEXA-Telegramme verzögern. Das Verhalten ist aus Upstream GroBro übernommen; der Fork hat es nicht ursprünglich verursacht.

**Anforderungen an ein zusammenhängendes Korrekturpaket:** lokale Verarbeitung darf nicht auf Cloud-Connect warten; Cloud-Weiterleitung muss eine ausdrücklich definierte FIFO-/Fehlersemantik haben. Eine unbeschränkte Queue und unkontrollierte zusätzliche Threads sind ausgeschlossen. Bestehende direkte Forwarding-Semantik und Cloud-Kommandos vorher gegen Upstream testen. Cloud aus muss weiterhin praktisch null Zusatzlast haben.

### P1 – MQTT-Publikations-Caches vs. tatsächliche Broker-Zustellung

**Belegt:** `grobro/model/mqtt_config.py:publish_succeeded` meldet lokalen Paho-Erfolg, nicht PUBACK. `grobro/ha/client.py` und `grobro/ha/performance.py` aktualisieren darunter Caches für Availability/States/Smart-Meter/Discovery. Nach Disconnect oder HA Birth werden zahlreiche Caches gelöscht und beim nächsten echten Paket neu aufgebaut.

**Risiko:** Paket wird lokal angenommen, aber vor bestätigter Broker-Zustellung verworfen; der unveränderte Payload kann bis zum nächsten Cache-Reset unterdrückt sein. Das Risiko ist bei QoS-0-Messwerten nicht mit einer PUBACK-Garantie lösbar, ohne QoS/Retain-Vorgaben explizit zu ändern.

**Abnahmekriterium:** Korrekte Differenzierung von Queue-Akzeptanz, bestätigt zugestellter Nachricht (wo QoS dies zulässt), aktueller Telemetrie und HA-Availability. Ein Reconnect darf keine älteren Daten als neu erfinden; wiederholte identische echte Frames müssen nach Recovery wieder publizierbar sein.

### P1 – zwei MQTT-Zustandsmaschinen, separate Zuständigkeiten

**Quellpfad:** `_config_read_ready` wird durch gültigen `c/#`-SUBACK gesetzt und bei Disconnect gelöscht; `config_reads_ready` prüft zusätzlich `is_connected()`.

**Zielpfad:** `_ha_mqtt_connected` wird nach CONNACK gesetzt. HA-Kommandos werden subscribiert; `_command_subscription_pending` wird schon bei lokal angenommener Subscription gelöscht, bei abgelehntem SUBACK wieder gesetzt. **Es gibt keinen dauerhaften, getrennten Wert „HA command SUBACK bestätigt“.** Diese Beobachtung belegt noch keinen realen Bedienfehler, macht aber den Status „controls ready“ nicht streng überprüfbar.

**Abnahmekriterium:** verbindliche Übergangstabelle für beide Broker und alle ACK-/Timeout-Fälle, einschließlich HA Birth ohne MQTT-Reconnect; keine zusätzlichen wiederkehrenden Geräteabfragen.

### P1 – Transport-Sicherheit

Quell-TLS bei aktivierter Option und Cloud-TLS deaktivieren derzeit die Zertifikatsprüfung (`ssl.CERT_NONE`, `tls_insecure_set(True)`). Das ist ein belegter Sicherheitsbefund. Eine kompatible Einführung validierter TLS-Verbindungen ist als **eigenes, gemeinsam getestetes** Paket zu planen und darf bestehende Growatt-Geräte nicht ohne Kompatibilitätsprüfung abklemmen.

### P2 – Zustands-Inventar, Cache-Eigentümerschaft und Persistenz

- `_device_last_seen`: zeitbasierte echte Geräteaktivität.
- `_last_availability`: zuletzt lokal akzeptierte HA-Availability.
- `_last_state_payload`, `_state_publish_cache`, `_last_holding_state`, `_smart_meter_state_cache`: getrennte Deduplizierung für Veröffentlichung.
- `_discovery_signature`, `_discovery_payload_cache`, `_discovery_cache`: HA-Gerätebeschreibung und Änderungsnachführung.
- `device_inventory`: Anzeigezustand in Ingress.
- `sensor_cache`: bis zu zwölf Stunden alte **ausgewählte, als gecacht gekennzeichnete** Batteriewerte; Leistungs-/Strommesswerte sind vom Backfill ausgenommen.

**Abnahmekriterium:** gemeinsame Tabelle je Cache: Besitzer, Auslöser, Löschen bei HA-Reconnect, Source-Reconnect, Geräte-Timeout, HA-Birth, Add-on-Restart. Persistierte Werte sind nie Beweis für Online/Live-Daten.

## Bereits vorhandene Tests – nicht duplizieren

`tests/test_mqtt_e2e.py` enthält reale MQTT-Prüfungen für NOAH/NEO, zwei getrennte Broker, Befehle, Smart Meter, LWT und Cloud. Die hinzugefügte Teststrecke für gleichzeitige NOAH-/NEO-Wiederherstellung wurde dort integriert. Weitere Tests in `tests/test_mqtt_state_matrix.py` sind Mock-Callback-Verträge, keine echte Netzwerkzustellung.

## Arbeitspakete und Freigabekriterien

1. **Paket A – Befundreproduktion:** vorhandene E2E-Suite vollständig ausführen und Cloud-Verzögerung/Publish-Verlust reproduzierbar simulieren; zusätzliche Tests nur für echte Abdeckungslücken.
2. **Paket B – Nachrichtenfluss/Cloud-Isolation:** Design und Umsetzung gegen bestätigte Upstream-Semantik; lokale Pipeline darf nicht blockieren; begrenzte Ressourcen und deterministische Stop-/Restart-Pfade.
3. **Paket C – MQTT-ACK-/Cache-Lebenszyklus:** getrennte Transport-, Subscription- und Publikationszustände; Recovery ohne fälschliche Online-/Messwertversprechen.
4. **Paket D – Security/Ingress:** TLS, Zugangskontrolle, Raw Dump und Supervisor-Optionen inkl. Kompatibilitätsmigration.
5. **Paket E – Gesamtvalidierung:** beide Broker, Cloud optional, mehrere gleichzeitige Geräte, mindestens alle 15 Szenarien der `docs/mqtt-state-matrix.md`; statische Prüfung, Tests, danach gesonderter HA-Praxistest.

**Release-Regel:** kein neues Release und keine isolierte Gerätekorrektur vor nachvollziehbarer Reproduktion, gemeinsamem Fix, bestandenen Tests und klar dokumentierten Rest-Risiken.

## Nachweisstand

Dies ist eine Quellcode- und Testarchitekturprüfung. Produktionscode wurde für diesen Bericht nicht verändert. Lokales pytest mit vollständigem Repository, `paho-mqtt`, `crc` und Mosquitto sowie Home-Assistant-Praxistests stehen aus. Keine Aussage „Tests bestanden“.
