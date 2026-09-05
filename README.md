# GroBro Register Debug

> Enhanced fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro) focused on Home Assistant robustness, runtime efficiency, passive protocol diagnostics and validated NOAH 2000 behavior.

GroBro is a bridge service that decodes Growatt MQTT packets and republishes device data and controls for Home Assistant.

This fork keeps the existing GroBro architecture and entity compatibility where possible, while adding targeted hardening and diagnostics across the supported device families.

## Current fork release

**2.8.0**

Reference upstream baseline for this release:

`robertzaage/GroBro` main @ `4797f8419bd574bcebd32d1a859569f97b58b774` (2026-08-08)

For the detailed, evidence-level comparison with upstream, see:

- [FORK_CHANGES.md](FORK_CHANGES.md)
- [CHANGELOG.md](CHANGELOG.md)

## Supported device-family routing

The fork uses one central runtime registry for the currently known serial prefixes:

- `0PVP` -> NOAH
- `0HVR` -> NEXA
- `QMN` / `PTQ` -> NEO
- `RAQ` -> ShineWeLink gateway
- `HAQ` -> SPF
- `ZGQ` -> MIN-XH2
- `VWQ` -> MOD

This keeps Home Assistant and Growatt MQTT register-map selection consistent.

## Main additions in this fork

- Hardened Home Assistant discovery, availability and reconnect behavior.
- Lower runtime allocation/timer/discovery overhead across device families.
- Centralized device-family detection and capability handling.
- Automatic clock synchronization at 00:00 and 12:00 local time for maps that expose `system_time` as config register 31.
- Atomic/sanitized device config persistence.
- Defensive Modbus/config parser validation.
- Safer Growatt Cloud forwarding/filter behavior.
- Passive register diagnostics and exact raw MQTT JSONL capture.
- NOAH 2000 validation from real captures, including the embedded `0x0103` block.

## Passive register diagnostics

Register debugging observes only traffic already received by GroBro. The logger does **not** actively scan the configured register range.

Register log:

`/share/GroBro/register_debug/registers.jsonl`

Optional raw MQTT log:

`/share/GroBro/dump/messages.jsonl`

Raw payloads are preserved exactly as Base64 inside JSONL records.

See [REGISTER_DEBUG.md](REGISTER_DEBUG.md) for details.

## NOAH validation

The NOAH-specific reverse-engineering and evidence levels are documented separately in [NOAH_VALIDATION.md](NOAH_VALIDATION.md).

The current NOAH map intentionally does not expose the experimental Home Assistant entities:

- MQTT IP
- Temperature PV1
- Temperature PV2
- System Temperature

NOAH Battery Health/SOH is emitted as a whole-number percentage.

## Installation as Home Assistant add-on

Use this repository:

[![Open your Home Assistant instance and add this GroBro repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcriticallimit%2FGroBro)

Or add manually:

`https://github.com/criticallimit/GroBro`

Then refresh the add-on store and install/update **GroBro Register Debug**.

Do not run two GroBro instances against the same Growatt MQTT source unless you deliberately configured separate MQTT client identities and understand the consequences.

## Current relevant defaults

```yaml
DUMP_MESSAGES: false
DUMP_DIR: /share/GroBro/dump
REGISTER_DEBUG: true
REGISTER_DEBUG_DIR: /share/GroBro/register_debug
REGISTER_DEBUG_MAX_REGISTER: 65535
REGISTER_DEBUG_CHANGES_ONLY: true
PUBLISH_SENSORS_RETAINED: false
MAX_SLOTS: 1
MAX_BAT: auto
AVAILABILITY_SENSOR: false
```

`REGISTER_DEBUG_MAX_REGISTER=65535` is only a passive capture filter. It does not cause GroBro to query registers `0-65535`.

## Automatic time sync

The old manual Sync Time button is not exposed by this fork.

For supported register maps, system time is synchronized automatically twice daily at local:

- 00:00
- 12:00

If `TZ` is left empty, the add-on launcher attempts to inherit the Home Assistant Supervisor timezone. A manually configured `TZ` remains an override.

## Testing status

The fork contains additional regression tests for parser validation, persistence safety, Home Assistant caching/reconnect behavior, device-family routing, time synchronization and NOAH diagnostics.

At the time of this release, GitHub Actions shows no workflow runs in this fork. The tests therefore must not be interpreted as automatically CI-passed; real runtime testing remains important.

## Upstream and license

This repository is a fork of GroBro by Robert Zaage and contributors. The original project license remains in [LICENSE](LICENSE).

Upstream project:

- [robertzaage/GroBro](https://github.com/robertzaage/GroBro)
