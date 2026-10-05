# Better GroBro

> **GroBro, optimized for Home Assistant.**

Better GroBro builds on [Robert Zaage's GroBro](https://github.com/robertzaage/GroBro) and adds a built-in Home Assistant interface, persistent battery assignments and practical tools for everyday operation.

---

## Better GroBro 3.2.1

### What Better GroBro offers

#### Easier Home Assistant setup

- Built-in configuration page directly inside Home Assistant, including MQTT settings and battery assignment
- Save settings and restart the add-on from the same interface
- Overview of detected devices, including their Growatt family and serial number
- Current-session add-on log viewer without leaving Better GroBro
- German, English, French, Spanish and Dutch interface and Home Assistant entity names, selected automatically from the Home Assistant language

#### Battery assignments that stay under your control

- Persistent NOAH Bat2/Bat3/Bat4 assignment by serial number when `KEEP_BATTERY_POSITION` is enabled, so a battery keeps its logical slot when the device reports a different physical order
- Optional manual Bat2/Bat3/Bat4 assignment by serial number in the built-in interface; your saved choices take priority over automatic assignment
- Saved assignments survive add-on restarts

#### More useful battery and firmware information

- NOAH Bat2/Bat3/Bat4 maximum and minimum cell-voltage sensors use the same Home Assistant metadata and scaling as Bat1
- NOAH Bat1–Bat4 cell-voltage sensors request three decimal places in Home Assistant, making millivolt differences easier to see
- Combined NOAH/NEXA firmware display includes the datalogger version when available, both in the firmware sensor and the Home Assistant device information
- Firmware changes refresh the Home Assistant device information automatically

#### More reliable everyday operation

- Improved recovery of MQTT connections and Home Assistant discovery after restarts
- More reliable “Read All” handling when replies are missing or a connection is interrupted
- Devices become unavailable after the configured telemetry timeout, helping you recognize stale readings; their Home Assistant entities remain in place and become available again when data returns
- Repeated identical telemetry avoids unnecessary MQTT state publications, while changed readings are still published
- Automatic clock synchronization for supported devices twice a day, in addition to the existing manual sync control
- Validation of NOAH/NEXA message lengths and register blocks before their readings are processed

#### Easier troubleshooting

- Clearer log entries identify source, target, device family, serial number and configuration register
- Optional passive register diagnostics for investigating device readings without sending additional device commands
- Diagnostic output can be limited to changed register values to reduce noise

### What stays familiar

Better GroBro keeps GroBro's MQTT bridge, Home Assistant discovery, supported device controls and optional Growatt Cloud forwarding. Local operation without cloud forwarding remains possible.

“Read All”, manual clock synchronization and automatic battery-count detection remain part of the familiar feature set. The improvements described above retain existing Better GroBro entity identifiers and command topics, keeping dashboards and automations connected to their entities.

---

## Installation

Add this repository to the Home Assistant Add-on Store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

Existing Better GroBro settings are retained when updating the installed add-on.

---

## Credits

Better GroBro is based on [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.
