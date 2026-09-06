# GroBro Register Debug

> Fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro) with targeted Home Assistant, performance, NOAH and diagnostic improvements.

GroBro is a bridge service that decodes Growatt MQTT packets and republishes device data and controls for Home Assistant.

## Current fork release

**3.0.1**

Reference upstream baseline:

`robertzaage/GroBro` main @ `4797f8419bd574bcebd32d1a859569f97b58b774`

The list below contains only changes in this fork compared with Robert Zaage's GroBro.

## Changes compared with robertzaage/GroBro

### Home Assistant

- Power entities with `device_class: power` and unit `W` are published as whole watts. Values such as `-0.4 W` therefore become `0 W` instead of appearing as `-0 W`.
- Home Assistant discovery is cached and is not rebuilt and republished for unchanged telemetry.
- Availability state is cached to reduce unnecessary MQTT traffic.
- Device identity handling is hardened so placeholder serial numbers made only of `X` characters cannot replace a valid identity.
- Persisted device configuration is restored by MQTT device ID.
- The manual **Sync Time** button and exposed **System Time** config entity are removed.
- Supported device clocks are synchronized automatically at 00:00 and 12:00 local time via config register 31.
- If the add-on `TZ` option is empty, the Home Assistant Supervisor timezone is inherited where available. An explicitly configured `TZ` remains an override.

### Runtime and performance

- Added a central device-family registry for NOAH, NEXA, NEO/PTQ, ShineWeLink/RAQ, SPF, MIN-XH2 and MOD.
- Added caching for device-family, MQTT topic/device-ID and Home Assistant battery-key resolution.
- Reduced allocations in Growatt scramble/unscramble processing.
- Added a fast path for the common single-Modbus-block telemetry case.
- Reused precompiled `struct.Struct` decoders for register values and protocol messages.
- Reduced repeated telemetry iteration and repeated Home Assistant rule evaluation.
- Replaced the bridge's 100 ms polling loop with event-driven waiting.
- Avoided DEBUG-only formatting work when DEBUG logging is disabled.

### NOAH

- Added validation based on real NOAH 2000 captures, including a three-module stack.
- Added passive parsing/diagnostics for the embedded NOAH `0x0103` holding-register block covering `R250-R374`.
- NOAH Battery Health / SOH is published as a whole-number percentage.
- Experimental NOAH entities `Temperature PV1`, `Temperature PV2`, `System Temperature` and `MQTT IP` are not exposed by the effective map.
- For validated NOAH `0PVP` status message `0x0104`, the existing Heater entity can use the validated heater byte from the status frame, with the previous register-derived value retained as fallback.

### Protocol and persistence hardening

- Added stricter validation for malformed or truncated Modbus and config traffic.
- Added validation for config-write device IDs, register numbers, ASCII values and protocol length limits.
- Invalid `TIME_HHMM` values are rejected instead of being published.
- Device configuration is written atomically and sensitive password/raw fields are excluded from persistence.
- Growatt Cloud configuration filtering is kept in the Growatt Cloud -> local device direction.
- Local MQTT publish results are checked and forwarding clients are cleaned up explicitly on shutdown.

### Diagnostics

- Added passive register diagnostics written to `/share/GroBro/register_debug/registers.jsonl`.
- Added optional raw MQTT capture to `/share/GroBro/dump/messages.jsonl` with exact Base64 payload preservation.
- Register diagnostics are change-aware to reduce processing overhead.
- Diagnostics are passive and do not actively scan register ranges.

### Add-on and CI integration

- Persistent `config_*.json` state is stored under `/data/GroBro`.
- Home Assistant add-on options are exported with shell-safe quoting.
- Fork images are published under `ghcr.io/criticallimit/grobro`.
- Multi-architecture builds cover `linux/amd64`, `linux/arm64` and `linux/arm/v7`.
- Fork CI runs Ruff and pytest across Python 3.11, 3.12 and 3.13.

For the detailed comparison and validation notes, see:

- [CHANGELOG.md](CHANGELOG.md)
- [FORK_CHANGES.md](FORK_CHANGES.md)
- [NOAH_VALIDATION.md](NOAH_VALIDATION.md)
- [REGISTER_DEBUG.md](REGISTER_DEBUG.md)

## Installation as Home Assistant add-on

Use this repository:

[![Open your Home Assistant instance and add this GroBro repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcriticallimit%2FGroBro)

Or add manually:

`https://github.com/criticallimit/GroBro`

Then refresh the add-on store and install/update **GroBro Register Debug**.

Do not run two GroBro instances against the same Growatt MQTT source unless separate MQTT client identities are deliberately configured.

## Upstream and license

This repository is a fork of GroBro by Robert Zaage and contributors. The original project license remains in [LICENSE](LICENSE).

Upstream project:

- [robertzaage/GroBro](https://github.com/robertzaage/GroBro)
