# Better GroBro

Better GroBro is a Home Assistant focused fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro).

This README lists only the user-relevant differences from Robert's GroBro.

## Better GroBro 3.1.29

Compared with Robert's GroBro, Better GroBro adds:

- A dedicated Home Assistant Ingress configuration UI for Better GroBro. It edits the official add-on options, validates them through the Supervisor, and keeps Home Assistant's native Configuration tab as a fallback.
- Automatic UI language selection for German, English, French and Spanish, based on the Home Assistant language, with English fallback.
- Stable NOAH/NEXA battery identities plus optional manual Bat2/Bat3/Bat4 assignment by detected serial number.
- More reliable Home Assistant state recovery after Home Assistant/MQTT restarts, including retained control values that would otherwise appear blank until refreshed.
- Reduced unnecessary Home Assistant/MQTT update traffic and lower runtime overhead without changing real value updates.
- Improved NOAH/NEXA handling, automatic supported-device clock synchronization, and optional passive diagnostics.

Everything else follows Robert's GroBro.

## Installation

Add this repository to the Home Assistant add-on store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

The existing GroBro-compatible add-on slug and configuration are retained for in-place updates.

## Upstream

Base project: [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.

Comparison baseline: `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23`.
