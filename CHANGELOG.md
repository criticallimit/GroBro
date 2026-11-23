# Better GroBro 3.3.22 — Differences from robertzaage/GroBro

## User-relevant differences

- Changed only INFO-log source descriptions for configuration-register values received in type 0x0119: one-register replies are logged as `single-register response`; compound TLV packets are logged as `compound config telegram`.
- This avoids implying NEO's unsolicited periodic R76+R5 packets were direct responses to an R76 query. Raw captures show NEO sent these every five minutes, while NOAH R76 messages were individual responses in the observed capture.
- Existing MQTT messages, callbacks, Home Assistant states, timeouts and polling remain unchanged.
- Extended existing compound-message regression and added a single-register origin test. Code static checks passed; pytest and live device tests remain pending.

---

# Better GroBro 3.3.21 — Differences from robertzaage/GroBro

## User-relevant differences

- Fixed a confirmed NEO 0x0103 parser misclassification seen in a November 23 raw MQTT dump. In this actual packet, the 16-byte field at offset 38 contained only the zero-padded ten-character suffix of the NEO serial, rather than a complete device ID. The generic Modbus parser previously treated ASCII `BZP4` there as registers 16986..20532 and issued a false "Truncated register block" warning.
- The 0x0103-special handling now also accepts an embedded 8+-character suffix of the verified NEO header/topic serial; complete known NOAH IDs are still supported. Unrelated embedded IDs and ordinary Modbus traffic stay on their existing parsing paths.
- Added positive and negative tests; existing NOAH 0x0103 test retained.
- No changes to MQTT forwarding, measurement registers, Wi-Fi reads, timeouts, or frequency of device communication.
- Static checks passed and the condition was matched against both 0x0103 frames found in the supplied raw dump. Full pytest and device verification remain pending.

---

# Better GroBro 3.3.20 — Differences from robertzaage/GroBro

## User-relevant differences

- Malformed or truncated Modbus register-block warnings now include sanitized structured diagnostics: protocol message type (two bytes at header offset 6), Modbus function, total packet size in bytes, and absolute block-start offset.
- No serial numbers, raw payload bytes or credentials are added to warnings. Existing warnings retain their register ranges and byte counts.
- No changes to actual Modbus data parsing, device command handling, MQTT communication, polling intervals or Wi-Fi measurements.
- Added synthetic BZP4 malformed-block regression and a valid NEO input packet regression.
- Eight structural checks passed. Full pytest and physical device verification pending.

---

# Better GroBro 3.3.19 — Differences from robertzaage/GroBro

## User-relevant differences

- Added **Raw MQTT Dump herunterladen** next to the existing log download button in the Ingress *Protokoll* tab.
- The new GET `/api/raw-dump` endpoint streams the unmodified `messages.jsonl` from the currently configured `DUMP_DIR` as a download without loading the entire file in memory.
- Handles not-yet-created or empty dumps with user-facing error messages. The route only accesses `messages.jsonl`, rejects symlinks outside the configured dump directory and remains behind existing Ingress client restrictions.
- Added a warning that raw packets may contain credentials or sensitive device information; raw capture itself still requires the existing diagnostics setting.
- Added regression tests for downloaded bytes, unavailable dumps, path traversal through symlinks and the download button.
- 11 structural checks passed; full Python pytest and Home Assistant device tests still pending.

---

# Better GroBro 3.3.18 — Differences from robertzaage/GroBro

## User-relevant differences

- NEO Modbus messages now enter the preliminary write-ack decoder only for Modbus function 6. Previously all NEO messages were parsed twice, producing duplicate truncated-block warnings for a single malformed packet.
- The standard Modbus decoder remains active once for telemetry and other messages; valid NEO function-6 acknowledgements retain their existing handling.
- Added regression coverage for single-pass non-write decoding and the NEO write-ack path.
- The underlying malformed frame whose register-range bytes resemble ASCII 'BZP4' has not yet been identified from raw packets. No speculative protocol offset change has been made.
- No new MQTT polls, timeouts or changes to WLAN state processing.
- Structural checks passed. Full pytest and real-device checks pending.

---

# Better GroBro 3.3.17 — Differences from robertzaage/GroBro

## User-relevant differences

- Full device configuration TLV packets now validate update interval R4 and Wi-Fi signal R76 *before* merging them into cached device metadata. Previously rejected values could still overwrite the metadata cache while being withheld from the Home Assistant state publication.
- Invalid or placeholder R4/R76 values in partial packets are omitted and cannot erase last known valid cached readings. Other legitimate device metadata still passes through unchanged.
- No new device commands, polling, broker changes or timeout modifications. Existing direct register response handling and diagnostic source logging are retained.
- Added parameterized regression scenarios for NEO, NOAH and NEXA plus a preservation test for previous valid values.
- Structural checks passed; full pytest and physical device tests remain pending.

---

# Better GroBro 3.3.16 — Differences from robertzaage/GroBro

## User-relevant differences

- WLAN logging now distinguishes an explicit successful local MQTT publication (return code 0) from an unconfirmed publish result, such as when the Home Assistant runtime is already stopped.
- Valid WLAN values still report their actual source (direct config-register response or full configuration telegram) independently of MQTT publication acceptance.
- No new periodic device reads, changes to source MQTT packets, reconnect behavior, or device-specific exceptions.
- Added a regression for suppressed MQTT publishing on shutdown; retained existing source logging tests.
- Static source checks passed; Python pytest and real-device checks remain pending.

---

# Better GroBro 3.3.15 — Differences from robertzaage/GroBro

## User-relevant differences

- Log received valid Wi-Fi signal (R76) in INFO with dBm measurement and source: direct register response or full device configuration telegram.
- Log HA MQTT local publication acceptance separately from device reception. This is not confirmation that Home Assistant has processed the update.
- Clarify R76 timeout: only the direct read has not received a matching reply within 10 seconds; separately received or MQTT-retained Wi-Fi values may still be shown.
- No changes to the device protocol, broker configuration, queue timeouts, Wi-Fi request frequency, or existing controls.
- Added targeted logging regression tests and restored the existing parametrized test association.
- Structural checks passed; automated pytest and real-device verification pending.

---

# Better GroBro 3.3.14 — Differences from robertzaage/GroBro

## User-relevant differences

- Detect locally rejected MQTT publications of config-state updates and log a clear warning instead of silently treating the update as successfully accepted.
- Validate direct register 4 (interval) and register 76 (Wi-Fi signal) responses before they update cached device metadata, consistent with already validated Home Assistant states.
- Keep processing subsequent valid values in compound packets when another entry is invalid.
- No additional periodic reads, retries, MQTT broker configuration changes or changes to device command packets.
- Added regression cases for NEO, NOAH and NEXA, including rejected MQTT publications.
- Targeted structural checks passed; pytest and device tests still pending.

---

# Better GroBro 3.3.13 — Differences from robertzaage/GroBro

## User-relevant differences

- Validate Update Interval (R4, Home Assistant minutes 0–60) and Wi-Fi Signal Strength (R76, signed dBm -120..-1) consistently for both direct config-read responses and full configuration TLV packets. Do not guess seconds-to-minutes conversions from ambiguous external examples.
- When a compound config read contains an invalid integer value, continue processing later valid entries instead of discarding the remainder of the message.
- Retain existing per-device read queue and timeout behavior; no additional periodic requests or speculative rejection of delayed valid values.
- Added regression scenarios across NOAH, NEO and NEXA and malformed compound packets.
- Structural checks passed; pytest and physical-device validation still pending.

---

# Better GroBro 3.3.12 — Differences from robertzaage/GroBro

## User-relevant differences

- Valid Update Interval (R4) and Wi-Fi Signal Strength (R76) values from full configuration TLV packets (message types 340, 341, 387 and ShineWeLink 0x0129) now update the same Home Assistant state topics as direct config-read responses (0x0119).
- All supported device families use the shared state path without modifying device MQTT commands or register mappings.
- Full configuration packets are not treated as acknowledgements of an outstanding single-register read and cannot advance the read queue.
- Publishing is limited to exposed R4/R76 values within defined entity/signal ranges; credentials and network configuration are excluded.
- Added regression scenarios for NEO, NOAH and NEXA, including ignored malformed values and sensitive fields.
- GitHub code/structural checks passed; automated pytest and real-device confirmation remain pending.

---

# Better GroBro 3.3.11 — Differences from robertzaage/GroBro

## User-relevant differences

- The Wi-Fi signal-strength register (R76) now follows the same ten-second non-response timeout on NEO, NOAH and NEXA; previously only NEO had that timeout.
- The existing common config read queue continues with the next setting when a device does not respond. Other configuration registers still use their original 60-second timeout.
- Existing MQTT commands, Home Assistant entity IDs, and real device readbacks remain unchanged.
- Added a NOAH/NEO/NEXA regression matrix for Wi-Fi timeouts, queue continuation and common discovery topics.
- Structural checks passed; end-to-end pytest and device verification are still pending.

---

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
