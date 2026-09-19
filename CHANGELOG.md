# Better GroBro 3.1.20 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## Home Assistant

- Suppresses unnecessary repeated telemetry, holding-state, discovery and availability publications while preserving real value changes.
- Publishes Home Assistant power sensors in whole watts and removes negative-zero presentation.
- Repairs stale retained discovery data during upgrades and keeps device/config identity stable across reconnects and restarts.
- Hides low-level/manual controls that Better GroBro replaces automatically, including MQTT IP, manual Sync Time and System Time.
- Keeps Robert's NEO Inverter Power discovery/control path intact.

## NOAH / NEXA

- Adds stable serial-based Bat2/Bat3/Bat4 assignment with `KEEP_BATTERY_POSITION=true`, including persistence across restarts and complete remapping of slot-specific values.
- Uses shared NOAH/NEXA protocol handling where applicable.
- Adds combined ShinePhone-style firmware reporting for NOAH/NEXA.
- Adds validated NOAH heater-state fallback and improved battery-count handling.
- Removes NOAH-only telemetry that was not considered reliable/useful for normal Home Assistant display.

## Time synchronization

- Automatically synchronizes supported device clocks at 00:00 and 12:00 local time.

## Reliability and safety

- Adds stricter validation for malformed/truncated Growatt packets and config commands.
- Avoids persisting/logging sensitive config data unnecessarily.
- Improves reconnect cleanup, timer cleanup, config restore and protection against overlapping Read All cycles.\n- Re-subscribes the complete Home Assistant command surface after every MQTT reconnect and clears interrupted Read All/config-read state, so commands continue working after Home Assistant/MQTT restarts.
- Improves Growatt Cloud forwarding/allowlist behavior and optional cloud configuration filtering.

## Runtime efficiency

- Reduces repeated parsing, allocations, JSON serialization, MQTT subscriptions and discovery work.
- Keeps diagnostics out of normal hot paths unless enabled.
- Uses a simplified production module structure with redundant wrapper modules removed.

## Optional diagnostics

- Adds passive register diagnostics and append-only raw MQTT JSONL capture.
- Diagnostics do not create additional device scans or writes.

All other behavior is inherited from Robert Zaage's GroBro.
