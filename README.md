# Better GroBro

> **GroBro, optimized for Home Assistant.**

Better GroBro builds on [Robert Zaage's GroBro](https://github.com/robertzaage/GroBro) and keeps its core behavior while making day-to-day use in Home Assistant cleaner, easier and more reliable.

---

## Better GroBro 3.1.64

### What Better GroBro adds

#### Easier Home Assistant setup

- Built-in configuration page directly inside Home Assistant
- Current-session add-on log viewer directly in the Better GroBro interface
- Automatic German, English, French, Spanish and Dutch interface and Home Assistant entity names
- Clear overview of detected Growatt families such as NOAH, NEO and NEXA

#### Better battery handling

- Publishes NOAH Bat2/Bat3/Bat4 maximum and minimum cell voltages with the same Home Assistant metadata and scaling as Bat1
- Requests three decimal places for NOAH Bat1–Bat4 cell-voltage sensors in Home Assistant so millivolt resolution is displayed consistently
- Stable NOAH/NEXA battery identities
- Optional manual Bat2/Bat3/Bat4 assignment by serial number

#### More reliable operation

- Improved NOAH/NEXA protocol handling
- Improved recovery after Home Assistant, MQTT or add-on restarts
- Stale measurement values become unavailable when telemetry stops, while entities remain in Home Assistant
- Lower unnecessary MQTT traffic without suppressing real value changes
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
