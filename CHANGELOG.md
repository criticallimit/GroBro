# Better GroBro 3.1.0 — Changes compared with robertzaage/GroBro

This changelog intentionally lists **only the material differences from Robert Zaage's GroBro**. It is not a historical release log.

Comparison baseline:

- Upstream: `robertzaage/GroBro`
- Upstream `main`: `4797f8419bd574bcebd32d1a859569f97b58b774`
- Comparison date: 2026-09-06

## Home Assistant

- Suppresses repeated publication of an identical complete telemetry state while preserving every real value change.
- Caches unchanged discovery and availability publications to reduce MQTT and Home Assistant churn.
- Clears state/discovery/availability caches after reconnect so fresh live state is republished.
- Publishes power sensors whose HA metadata is `device_class: power` and unit `W` as whole watts; raw Growatt decoding and energy counters remain unchanged.
- Removes negative-zero presentation such as `-0 W`.
- Uses conservative automatic battery-count handling instead of assuming the maximum battery count when unknown.
- Keeps Home Assistant device identity stable and avoids replacing it with invalid placeholder serials.

## NOAH

- Adds hardware-validated handling for NOAH multi-battery telemetry and battery count.
- Preserves the existing Heater entity but can use the validated heater byte from NOAH `0x0104` cyclic status traffic when available; unsupported packets fall back to the existing register-derived state.
- Adds passive decoding/observation support for NOAH holding/config traffic used during validation without active register scanning.
- Removes fork-tested NOAH entities that were not useful/reliable enough for normal Home Assistant presentation: `Temperature PV1`, `Temperature PV2`, `System Temperature` and `MQTT IP`.

## Time synchronization

- Removes the manual `Sync Time` button and exposed `System Time` entity.
- Automatically synchronizes supported device clocks at 00:00 and 12:00 local time through config register 31.
- Determines support from the active register map and does not write directly to RAQ/ShineWeLink gateways.
- Uses the Home Assistant/Supervisor timezone when `TZ` is not explicitly configured.

## Protocol and configuration safety

- Adds stricter validation for malformed or truncated Modbus/config packets, register ranges, trailers and value lengths.
- Centralizes and validates Growatt config read/write packet construction (`0x0119` / `0x0118`).
- Rejects invalid config device IDs, register numbers and unsupported config value encodings before publishing a packet.
- Avoids normal logging of config values that may contain credentials.
- Excludes sensitive password/raw fields from persisted device configuration and uses safer persistence behavior.

## Growatt Cloud forwarding

- Makes `GROWATT_CLOUD` false/true/allowlist handling consistent.
- Keeps optional cloud configuration filtering in the Cloud → local device direction.
- Keeps forwarding clients instance-local and cleans them up explicitly on shutdown.
- Checks local MQTT publish results instead of silently ignoring immediate publish failures.

## Runtime efficiency and reliability

- Adds cached device-family and device-ID resolution instead of repeating equivalent prefix/topic parsing across hot paths.
- Reduces repeated allocations and parsing work in Growatt scramble/unscramble, Modbus decoding and Home Assistant telemetry preparation.
- Uses a single-pass HA telemetry preparation path and cached static register rules.
- Avoids DEBUG-only payload formatting work unless DEBUG logging is enabled.
- Uses direct MQTT v5 `UserProperty` access on the common path.
- Uses event-driven shutdown waiting instead of a 100 ms polling loop.
- Uses daemon helper timers with explicit cleanup and lower timeout timer churn.
- Restores persisted device configuration by MQTT device ID.

## Optional diagnostics

- Adds passive register diagnostics under `/share/GroBro/register_debug/`.
- Adds an append-only raw MQTT JSONL capture under `/share/GroBro/dump/messages.jsonl` with lossless Base64 payload storage.
- Diagnostics are opt-in and passive: they do not create extra register scans or device writes.

## Add-on / CI

- Uses the Better GroBro add-on name while retaining the existing add-on slug for in-place updates.
- Persists runtime configuration data under the add-on data directory.
- Adds fork CI on Python 3.11, 3.12 and 3.13 with Ruff, pytest and coverage checks.
- Publishes Better GroBro container builds through the fork's own GHCR pipeline.

All other functionality is inherited from Robert Zaage's GroBro and is intentionally not duplicated in this changelog.
