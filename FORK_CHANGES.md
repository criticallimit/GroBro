# GroBro 3.0.0 fork changes vs. robertzaage/GroBro

This document is the detailed technical companion to `CHANGELOG.md`. It describes the material differences between `criticallimit/GroBro` 3.0.0 and Robert Zaage's upstream GroBro.

## Reference baseline

- Upstream repository: `robertzaage/GroBro`
- Upstream `main` / merge base used for this release: `4797f8419bd574bcebd32d1a859569f97b58b774` (2026-08-08)
- Fork release: `3.0.0`
- Comparison date: 2026-09-06
- Fork status before the 3.0.0 release metadata commits: 185 commits ahead, 0 behind

The fork keeps normal Growatt MQTT and Home Assistant compatibility as the priority while adding robustness, lower runtime overhead, passive diagnostics and hardware-validated NOAH behavior.

## 1. Central device-family handling

A central device-family registry is the active source for serial-prefix detection, register-map selection and capabilities.

Families handled by the registry:

- `0PVP` -> NOAH
- `0HVR` -> NEXA
- `QMN` / `PTQ` -> NEO
- `RAQ` -> ShineWeLink gateway
- `HAQ` -> SPF
- `ZGQ` -> MIN-XH2
- `VWQ` -> MOD

Resolved families are cached so Home Assistant and Growatt MQTT do not repeatedly perform independent prefix decisions.

## 2. Home Assistant robustness and identity

Compared with upstream, the fork adds or changes the following behavior:

- discovery payload caching; unchanged discovery is not rebuilt/republished for every telemetry packet,
- availability-state caching and reconnect invalidation,
- retained Online state when the optional connectivity sensor is enabled,
- lower-churn timeout handling and explicit timer cleanup,
- stable MQTT-device identity for Home Assistant,
- rejection of placeholder serial values consisting only of `X` characters,
- config persistence keyed by MQTT device ID,
- suppression of invalid/missing local-IP configuration URLs,
- suppression of stale/invalid software-version publication when no real version is available,
- cleanup of internal-only discovery fields before publication.

Existing entity IDs, unique IDs, MQTT state topics and device identifiers are intentionally kept stable wherever possible.

## 3. Automatic clock synchronization

The manual Home Assistant `Sync Time` button and exposed `System Time` entity are removed.

Supported devices are synchronized automatically at:

- 00:00 local time
- 12:00 local time

Support is derived from the active register map exposing config register 31 as a string time register. NOAH, NEXA, NEO/PTQ, SPF, MIN-XH2 and MOD are supported by their active maps. RAQ/ShineWeLink gateways are not written directly; a detected PTQ inverter behind the gateway is handled as NEO.

If the add-on `TZ` option is empty, the runtime attempts to inherit the Home Assistant Supervisor timezone. An explicit `TZ` remains an override.

## 4. NOAH 2000 validation and corrections

The fork includes validation against real traffic from a three-module NOAH 2000 stack.

Validated/strengthened NOAH behavior includes:

- battery count and individual battery SOC/temperature handling,
- stack SOC/SOH and energy counters,
- PV voltage/current telemetry,
- cell-voltage extrema,
- battery cycle count,
- output voltage and firmware encoding,
- passive decoding of embedded `0x0103` register data covering `R250-R374`.

Fork-specific presentation/cleanup:

- NOAH SOH is emitted as a whole-number percentage,
- `Temperature PV1`, `Temperature PV2`, `System Temperature` and `MQTT IP` are removed from the effective NOAH Home Assistant map,
- passive watch logging remains available for unknown NOAH register values without active scanning.

### NOAH Heater

The existing Home Assistant `Heater` entity is retained. For NOAH `0PVP` status message `0x0104`, the fork uses the observed heater byte at absolute decrypted offset 108 when the value fits the existing `0..15` bitmask vocabulary. Unsupported packets/values leave the previous register-derived state as fallback.

Packets too short to contain the validated heater byte are rejected before the extra Heater-specific descramble step.

This Heater mapping is based on observed traffic and community reverse engineering, not presented as official Growatt Modbus documentation.

## 5. Passive diagnostics

The fork adds passive diagnostics that operate only on traffic already received by GroBro.

Register observations:

`/share/GroBro/register_debug/registers.jsonl`

Raw MQTT captures:

`/share/GroBro/dump/messages.jsonl`

Differences from upstream include:

- one append-only raw JSONL file with exact Base64 payload preservation instead of many individual binary files,
- parsed register JSONL records with signed/unsigned/hex information,
- change-only logging with the first observation retained,
- whole-block rejection before per-register unpacking when an unchanged block is seen,
- no active register scanning caused by diagnostics.

Normal defaults are deliberately low-overhead:

- `LOG_LEVEL=ERROR`
- `DUMP_MESSAGES=false`
- `REGISTER_DEBUG=false`

## 6. Protocol and parser hardening

The fork adds stricter handling for malformed/truncated protocol traffic:

- Modbus message length/range validation,
- valid final single-register block handling,
- supported trailer-byte handling,
- safe register-data bounds checks,
- invalid numeric-length rejection,
- invalid `TIME_HHMM` rejection,
- additional config read/write response length checks,
- safer handling of holding-register definitions without a real Growatt register,
- separation of malformed-message errors from unexpected exceptions.

## 7. Config-write and persistence safety

Additional safeguards include:

- validation of device IDs and register numbers before packet construction,
- ASCII and protocol-length validation for config values,
- no normal logging of config values that may contain credentials,
- atomic persisted-config writes,
- exclusion of sensitive password/raw fields from persisted configuration,
- tighter file permissions where supported.

## 8. Growatt Cloud forwarding

Fork-specific forwarding behavior includes:

- consistent false-value handling for `GROWATT_CLOUD`,
- continued support for comma-separated device allowlists,
- cloud config filtering applied in the Growatt Cloud -> local device direction,
- loop prevention through forwarded-message properties,
- instance-local forwarding clients with shutdown cleanup,
- publish-result checks for local MQTT failures.

The upstream-compatible permissive TLS behavior is intentionally retained to avoid breaking existing installations.

## 9. Runtime performance

The fork contains a set of low-risk performance optimizations designed to preserve supported semantics:

- one-buffer Growatt scramble/unscramble,
- rolling seven-byte XOR mask index instead of per-byte modulo,
- single-Modbus-block fast path,
- no redundant immutable-bytes copies,
- precompiled `struct.Struct` objects for register values, Modbus headers/metadata/blocks and commands,
- reduced repeated Pydantic attribute access during register decoding,
- cached device-family, MQTT device-ID and battery-key parsing,
- single-pass Home Assistant telemetry preparation,
- cached static per-register Home Assistant rules (ENUM, `total_increasing`, battery temperature),
- no ENUM mapper call for non-ENUM values,
- discovery and availability caching,
- reduced timeout/config timer churn and daemon helper timers,
- DEBUG-only payload hex/property work skipped at normal log levels,
- direct MQTT v5 `UserProperty` access on the normal path,
- event-driven bridge idle wait instead of a 100 ms polling loop.

The larger architectural change of removing Pydantic model construction entirely from telemetry paths has intentionally not been made because it would carry substantially more regression risk.

## 10. Add-on runtime integration

The fork additionally:

- persists `config_*.json` below `/data/GroBro`,
- exports add-on options with shell-safe quoting,
- keeps application code explicitly on `PYTHONPATH`,
- derives timezone from Supervisor when `TZ` is unset,
- includes fork-specific German and English add-on translations/configuration text.

## 11. Tests and CI

The fork adds substantial regression coverage for areas including:

- central family resolution,
- malformed Modbus/config traffic,
- command and register bounds,
- config persistence/security,
- scramble/unscramble equivalence,
- discovery and availability caching,
- reconnect behavior,
- automatic clock sync,
- NOAH removed entities and Heater override,
- embedded NOAH `0x0103`,
- passive register diagnostics,
- single-pass Home Assistant telemetry rules,
- event-driven shutdown behavior.

CI validates Ruff plus the full pytest suite on Python 3.11, 3.12 and 3.13 with the configured coverage threshold. Superseded branch runs are cancelled automatically.

## 12. Container publishing

The fork publishes to its own GHCR namespace:

`ghcr.io/criticallimit/grobro`

The workflow builds:

- `linux/amd64`
- `linux/arm64`
- `linux/arm/v7`

After CI succeeds, the Docker workflow checks out the exact successful CI `head_sha` and uses `context: .`. This was explicitly validated in the build logs: Buildx received the local workspace context and recorded the same commit as `vcs:revision`, ensuring the container is built from the exact commit that passed CI.

## Evidence level

- NOAH items described as hardware-validated were checked against captured traffic from the available three-module system.
- The NOAH Heater override is empirical/community-reverse-engineered rather than official Growatt documentation.
- NEO has additional repository packet fixtures, including clock-setting traffic.
- NEXA, SPF, MIN-XH2 and MOD shared-path improvements rely on their existing register maps/tests unless separately hardware-validated.
- Passing CI validates software behavior against repository tests; it does not substitute for physical validation of every Growatt model/firmware.

For detailed NOAH evidence and diagnostics formats, see `NOAH_VALIDATION.md` and `REGISTER_DEBUG.md`.
