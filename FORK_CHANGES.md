# GroBro fork changes vs. robertzaage/GroBro

This document summarizes the material differences between this fork and the upstream GroBro project by Robert Zaage and contributors.

Reference baseline for this release:

- Upstream repository: `robertzaage/GroBro`
- Upstream `main`: `4797f8419bd574bcebd32d1a859569f97b58b774` (2026-08-08)
- Fork release: `2.8.3`
- Comparison date: 2026-09-05

The goal of this fork is to keep GroBro's normal MQTT/Home Assistant behavior compatible while improving robustness, runtime efficiency and diagnostics, and while validating additional NOAH 2000 behavior from real captures.

## 1. Central device-family handling

A central device-family registry now defines the active mapping from device serial prefix to:

- device family name,
- register map,
- supported capabilities,
- dynamic PV detection behavior.

The active families are:

- `0PVP` -> NOAH
- `0HVR` -> NEXA
- `QMN` / `PTQ` -> NEO
- `RAQ` -> ShineWeLink gateway
- `HAQ` -> SPF
- `ZGQ` -> MIN-XH2
- `VWQ` -> MOD

This replaces multiple independent runtime prefix decisions with one active source of truth and reduces the risk of Home Assistant and Growatt MQTT handling the same serial differently.

## 2. Home Assistant robustness

The Home Assistant bridge was hardened while preserving existing entity identities and topics where possible.

Notable changes include:

- per-instance runtime caches instead of relying on shared mutable class state,
- discovery caching so the complete device discovery payload is not rebuilt on every telemetry packet,
- availability-state caching to avoid repeatedly publishing identical retained online/offline state,
- the optional Online binary sensor is always published retained so it survives Home Assistant/MQTT reconnect timing,
- discovery/availability publish caches are invalidated after MQTT reconnect so retained state is recreated after broker restarts,
- lower-churn device timeout handling: one timer per device instead of cancelling/recreating a timer for every telemetry packet,
- graceful timer cleanup during shutdown,
- persisted device config is restored by MQTT device ID,
- device serial identity remains stable while using the configured serial as device metadata when available,
- placeholder serial values consisting only of `X` characters are discarded instead of replacing the stable MQTT device identity,
- invalid or missing local IP values are no longer used as Home Assistant configuration URLs,
- internal GroBro-only discovery fields are cleaned before publishing,
- stale/invalid software-version publication is suppressed when no actual version is known.

## 3. Automatic clock synchronization

The manual Home Assistant `Sync Time` button and the Home Assistant `System Time` config entity are no longer exposed.

For supported device families, GroBro synchronizes config register `31` (`system_time`, STRING) automatically twice per local day:

- 00:00
- 12:00

Time-sync support is derived from the active register map rather than being maintained as an unrelated hard-coded feature flag.

Current supported families are NOAH, NEXA, NEO, SPF, MIN-XH2 and MOD because their active maps expose `system_time` as config register 31. The RAQ ShineWeLink gateway itself is not written; a detected PTQ inverter behind it is treated as NEO.

If the add-on `TZ` option is empty, the launcher attempts to use the Home Assistant Supervisor timezone so scheduled writes use Home Assistant local time. An explicitly configured `TZ` remains an override.

## 4. NOAH 2000 telemetry validation and corrections

NOAH behavior was validated against real captures from a three-module NOAH 2000 stack running firmware 19.19.14.

Strongly validated fields include:

- battery count (`R12`),
- system state,
- total and individual battery SOC,
- individual battery temperatures,
- PV voltage/current values,
- energy counters,
- battery cycle count,
- stack SOH,
- cell voltage extrema,
- output voltage,
- firmware encoding.

The fork also validates an embedded NOAH `0x0103` holding-register block covering `R250-R374` and documents observed scheduling registers.

Additional NOAH-specific presentation/cleanup decisions in this fork:

- `Battery Health` / SOH is emitted as an integer percentage instead of a float with `.0`,
- experimental `Temperature PV1`, `Temperature PV2` and `System Temperature` entities were removed from the effective NOAH Home Assistant map,
- `MQTT IP` was removed from the effective NOAH config map,
- passive watch logging remains for unknown `R299-R304` values without issuing active writes or scans.

The existing Home Assistant `Heater` entity is preserved. For NOAH `0PVP` status messages of type `0x0104` (decimal 260), the fork reads the observed heater-status byte at payload offset 84 after the 24-byte header (absolute offset 108). Values `0..15` override the older register-17-derived heater value while reusing the existing enum/bitmask representation. Unsupported packets or invalid values leave the old register-based value as fallback. This is an empirical NOAH status-frame mapping and is not presented as official Growatt Modbus documentation.

These NOAH-specific removals and overrides do not change the corresponding definitions for other device families.

## 5. Passive register diagnostics

The fork adds passive register diagnostics that operate only on traffic already received by GroBro.

Features include:

- parsed register observations written as JSONL,
- change-only mode while still recording the first observation,
- register number, unsigned/signed values, hex representation and byte-level information,
- passive NOAH `0x0103` capture and watch groups,
- no active register scanning caused by the debug logger.

Register log:

`/share/GroBro/register_debug/registers.jsonl`

Raw MQTT capture can also be enabled and is stored in one append-only JSONL file with exact Base64 payload preservation:

`/share/GroBro/dump/messages.jsonl`

This replaces the old behavior of creating large numbers of individual binary dump files in this fork.

## 6. Parser and protocol hardening

Growatt packet handling was made more defensive against malformed or truncated traffic.

Notable changes include:

- safer Modbus message length/range validation,
- final single-register blocks are accepted correctly,
- supported trailer bytes are handled without rejecting an otherwise valid block,
- safe register-data bounds checks,
- malformed numeric register lengths return no value instead of raising into the MQTT callback,
- invalid `TIME_HHMM` values are rejected,
- config read/write response parsing has additional length validation,
- malformed messages are separated from unexpected exceptions in logs,
- invalid config integer values do not crash message processing,
- holding-register definitions without a real Growatt register are skipped safely in receive paths.

## 7. Config-write and persistence safety

Config handling was hardened to reduce accidental corruption or leakage.

Changes include:

- device IDs and register numbers are validated before config packets are built,
- config write values must be ASCII and within protocol length limits,
- config values are not written to normal logs,
- device config persistence is atomic using a temporary file and replace operation,
- sensitive `password` and raw fields are excluded from persisted config,
- saved config permissions are tightened where supported.

## 8. Growatt Cloud forwarding robustness

Cloud forwarding semantics were clarified and hardened:

- `GROWATT_CLOUD=false`, `0`, `no`, `off` and an empty value now consistently mean disabled,
- a non-boolean value remains supported as a comma-separated device allowlist,
- configuration/control filtering is applied in the Growatt Cloud -> local device direction,
- configuration writes are blocked when the cloud config filter is enabled while normal telemetry forwarding can continue,
- forwarded HA/Growatt messages are marked and skipped to avoid loops,
- forwarding clients are instance-local and cleaned up on shutdown,
- local MQTT publish failures are checked and logged when Paho reports an error.

TLS certificate verification behavior remains compatible with upstream by default; it has deliberately not been changed to a strict default that could break existing Growatt/local TLS installations.

## 9. Runtime performance improvements

The fork includes several low-risk hot-path optimizations that apply across device families:

- Growatt scramble/unscramble uses one-pass/preallocated bytearray processing instead of repeated immutable byte concatenation,
- Modbus parser membership checks and byte slicing were reduced,
- static unpack/type lookup structures are reused instead of rebuilt per value,
- Home Assistant discovery is rebuilt only when its effective signature changes,
- repeated identical availability publications are skipped,
- device timeout timer churn is reduced,
- device-family lookup uses a prepared prefix table and caches resolved serial IDs.

The larger architectural optimization of removing Pydantic object construction from telemetry hot paths has intentionally not been done yet because it is more invasive and should be benchmarked before adoption.

## 10. Add-on/runtime behavior

The Home Assistant add-on launcher now:

- keeps persistent `config_*.json` state under `/data/GroBro`,
- exports add-on options with shell-safe quoting,
- keeps application code explicitly on `PYTHONPATH`,
- derives timezone from Home Assistant Supervisor when `TZ` is empty where possible.

Default debug options were adjusted for the current fork. The effective `REGISTER_DEBUG_MAX_REGISTER` default is `65535`; this is only a passive capture filter and does not make GroBro scan that register range.

## 11. Tests, CI and release pipeline

Additional tests cover areas including:

- malformed Modbus message handling,
- trailer handling,
- register value validation,
- config persistence security,
- config packet validation,
- scramble/unscramble equivalence over large packets,
- Home Assistant discovery caching,
- availability retained behavior and reconnect invalidation,
- central device-family resolution,
- time-sync capability consistency,
- NOAH removed entities,
- NOAH Heater status-frame override,
- NOAH embedded `0x0103` parsing,
- passive register debug behavior.

GitHub Actions is enabled for this fork. The 2.8.3 code path has been validated with Ruff and the full pytest suite on Python 3.11, 3.12 and 3.13, with coverage above the configured 85% threshold. The Docker workflow then successfully built the image for `linux/amd64`, `linux/arm64` and `linux/arm/v7` and pushed it to the fork-owned `ghcr.io/criticallimit/grobro` namespace. Superseded CI runs on the same branch are cancelled automatically to reduce runner churn.

Runtime/hardware testing remains important because CI cannot validate every physical Growatt model or firmware revision.

## 12. What intentionally remains upstream-compatible

This fork does not try to remove genuine protocol-family differences. Special handling remains where the protocol requires it, for example:

- NOAH/NEXA FE19/config and 0x0103-style messages,
- RAQ ShineWeLink -> PTQ inverter routing,
- family-specific register maps,
- compatibility-oriented TLS defaults.

Existing Home Assistant entity IDs, unique IDs, state topics and device identifiers are kept stable wherever possible to avoid unnecessary registry churn and broken automations.

## Evidence level

This document distinguishes implementation from hardware validation:

- NOAH 2000 items described as validated were checked against captured traffic from the available three-module system.
- The NOAH Heater override is based on observed status-frame behavior and community reverse engineering, not an official Growatt register specification.
- NEO behavior has additional repository fixtures including a real `NeoSetDateTime.bin` packet.
- NEXA, SPF, MIN-XH2 and MOD family-wide improvements are based on their existing GroBro register maps and shared runtime paths unless separately stated; they have not all been hardware-tested in this fork.
- Passing CI confirms software behavior against the repository tests; it does not upgrade unsupported family fixtures into hardware evidence.

For raw reverse-engineering evidence and register-specific NOAH findings, see `NOAH_VALIDATION.md` and `REGISTER_DEBUG.md`.
