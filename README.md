# Better GroBro

Better GroBro is a Home Assistant focused fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro).

This README lists only the relevant differences from Robert's GroBro.

## Better GroBro 3.1.22

Compared with Robert's GroBro, Better GroBro adds:

- Reduced Home Assistant/MQTT churn and lower runtime overhead by avoiding unnecessary repeated state/discovery publications and repeated processing.
- Stable NOAH/NEXA battery identities with `KEEP_BATTERY_POSITION=true`, so Bat2/Bat3/Bat4 do not change identity when the battery chain is re-enumerated.
- Improved NOAH/NEXA handling, including combined firmware display, validated NOAH heater-state handling and shared family/protocol behavior.
- Automatic device clock synchronization at 00:00 and 12:00 local time for supported devices.
- Cleaner Home Assistant presentation, including removal of low-level/manual controls that are no longer needed and whole-watt power values.
- More robust reconnect, timer, config persistence, packet validation and Growatt Cloud forwarding behavior, including forced one-time state republishing after Home Assistant Core restarts even when values themselves did not change.
- Optional passive diagnostics for register/raw MQTT analysis without additional device polling or writes.

Everything else follows Robert's GroBro.

## Installation

Add this repository to the Home Assistant add-on store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

The existing GroBro-compatible add-on slug and configuration are retained for in-place updates.

## Upstream

Base project: [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.

Comparison baseline: `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23`.

See [CHANGELOG.md](CHANGELOG.md) for the technical differences.
