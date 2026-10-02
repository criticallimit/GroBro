# Better GroBro 3.1.70 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## Reliability fixes in this release

- MQTT publication failures no longer interrupt independent telemetry, device information or received configuration responses.
- Saved battery assignments and detection history are protected against transient file-read errors; manual choices remain authoritative.
- Read All can recover from rejected MQTT requests and interrupted sequences.
- Device and background timer failures leave processing and subsequent retries usable.
- Register diagnostics retain changes correctly when received register blocks overlap.
- Reduced repeated JSON processing, buffer copies and register searches; optimized configuration and NOAH/NEXA parsing.

Entity identifiers, supported device controls and normal device protocol behavior remain unchanged. Validation: 933 tests passed; CI passed on Python 3.11, 3.12 and 3.13.

## User-relevant differences

### Home Assistant integration

- Built-in Better GroBro configuration interface inside Home Assistant.
- Automatic German, English, French, Spanish and Dutch localization for the interface and Home Assistant entity display names.
- Device overview for detected Growatt families such as NOAH, NEO and NEXA.
- Integrated log viewer for the current Better GroBro process.
- User-friendly log entries clearly identify the source, target, device family, serial number and config register.

### Battery handling

- Stable NOAH/NEXA battery positions based on battery serial numbers.
- Optional manual Bat2/Bat3/Bat4 assignment.
- Additional NOAH Battery 2/3/4 maximum and minimum cell-voltage sensors.
- Consistent three-decimal display precision for NOAH Bat1–Bat4 cell-voltage sensors.

### Reliability and operation

- Improved NOAH/NEXA protocol handling compared with the upstream baseline.
- Improved Home Assistant, MQTT and add-on restart/reconnect recovery.
- Device availability handling prevents stale measurement values from remaining active when telemetry stops.
- Reduced unnecessary MQTT/Home Assistant traffic without suppressing real state changes.
- Supported-device clock synchronization and optional diagnostics.

All other behavior is inherited from Robert Zaage's GroBro.
