# Better GroBro 3.1.58 — Differences from robertzaage/GroBro

Comparison baseline: `robertzaage/GroBro` main at `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23` (2026-09-18).

## User-relevant differences

### Home Assistant integration

- Built-in Better GroBro configuration interface inside Home Assistant.
- Automatic German, English, French, Spanish and Dutch localization for the interface and Home Assistant entity display names.
- Device overview for detected Growatt families such as NOAH, NEO and NEXA.
- Integrated log viewer for the current Better GroBro process.

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
