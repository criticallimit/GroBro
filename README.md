# Better GroBro

> **GroBro, optimized for Home Assistant.**

Better GroBro is based on [Robert Zaage's GroBro](https://github.com/robertzaage/GroBro) and keeps its core behavior while extending it for tighter Home Assistant integration and improved NOAH/NEXA support.

---

## Better GroBro 3.1.56

### Differences from Robert Zaage's GroBro

#### Home Assistant integration

- Built-in configuration interface directly inside Home Assistant
- Automatic German, English, French, Spanish and Dutch interface and Home Assistant entity names
- Overview of detected Growatt device families such as NOAH, NEO and NEXA
- Integrated log viewer for the currently running Better GroBro session

#### Battery handling

- Stable NOAH/NEXA battery positions by serial number
- Optional manual Bat2/Bat3/Bat4 assignment
- Additional NOAH Bat2/Bat3/Bat4 maximum and minimum cell-voltage sensors
- Consistent millivolt-resolution display for NOAH Bat1–Bat4 cell-voltage sensors

#### Reliability and operation

- Improved NOAH/NEXA protocol handling
- Improved recovery after Home Assistant, MQTT or add-on restarts
- Device availability handling prevents stale measurement values from remaining active when telemetry stops
- Reduced unnecessary MQTT/Home Assistant traffic while preserving real value changes
- Supported-device clock synchronization and optional diagnostics

Everything else continues to follow Robert's GroBro.

---

## Installation

Add this repository to the Home Assistant Add-on Store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

Existing GroBro-compatible settings are retained for in-place updates.

---

## Credits

Better GroBro is based on [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.
