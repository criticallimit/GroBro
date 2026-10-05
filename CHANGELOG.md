# Better GroBro 3.2.1 — User interface update

## User-relevant changes

- Reworked the built-in Ingress overview to match the compact Better GroBro dashboard layout.
- Added live Bat1–Bat4 state of charge and battery temperature display for NOAH systems.
- Added live Wi-Fi signal strength display for detected devices, including NEO gateway-to-inverter propagation.
- Improved device icon proportions, text readability and consistent card alignment.
- Existing configuration, battery assignment, MQTT, diagnostics and log functions remain available.

---

# Better GroBro 3.2.0 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## Reliability fixes in this release

- MQTT connections recover without blocking add-on startup; connection and subscription failures remain visible without repeated log noise.
- Configuration saves preserve unrelated settings during concurrent updates and validate MQTT options before restart.
- Read All, compound configuration responses and NEO readback continue after independent processing failures.
- Smart-meter traffic refreshes device availability, including unchanged readings.
- Diagnostic storage failures no longer prevent startup; pending acknowledgement tracking is bounded.
- Home Assistant discovery construction is simplified, and temporary language API failures preserve established entity names.
- Release images can recover after interrupted publication; prereleases no longer replace the stable image tag.

Entity identifiers, supported device controls, manual battery assignments and normal device protocol behavior remain unchanged. Validation: 1,020 tests passed; CI passed on Python 3.11, 3.12 and 3.13.

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
