# GroBro 3.0.1 — Differences from robertzaage/GroBro

This changelog intentionally contains no historical release log. It documents only the material differences between `criticallimit/GroBro` 3.0.1 and the current upstream baseline used for this release.

Comparison baseline:

- Upstream repository: `robertzaage/GroBro`
- Upstream `main` / merge base: `4797f8419bd574bcebd32d1a859569f97b58b774`
- Comparison date: 2026-09-06
- Fork status before the 3.0.0 release metadata commits: 185 commits ahead, 0 behind

## Runtime and performance

- Added a central device-family registry for NOAH, NEXA, NEO/PTQ, ShineWeLink/RAQ, SPF, MIN-XH2 and MOD, replacing duplicated prefix decisions in multiple runtime paths.
- Added cached device-family, MQTT topic/device-ID and Home Assistant battery-key resolution.
- Reworked Growatt scramble/unscramble to use one mutable buffer and a rolling XOR-mask index instead of repeated immutable allocations and per-byte modulo operations.
- Added a fast path for the common single-Modbus-block telemetry case.
- Reused precompiled `struct.Struct` decoders for register values, Modbus messages, metadata and Modbus commands.
- Avoided redundant `bytes(...)` copies when register data is already immutable bytes.
- Reduced repeated Pydantic attribute access in per-register decoding.
- Added a single-pass Home Assistant telemetry preparation path instead of repeatedly iterating and allocating lists from the same payload.
- Cached static Home Assistant register rules such as ENUM, `total_increasing`, battery-temperature handling and whole-watt power classification per register map.
- Skipped ENUM mapping calls entirely for non-ENUM sensors.
- Added discovery-signature caching so unchanged Home Assistant discovery is not rebuilt and republished on every telemetry packet.
- Added availability-state caching and lower-churn timeout handling.
- Converted helper/config/timeout timers to daemon timers while retaining explicit shutdown cleanup.
- Replaced the bridge's 100 ms polling loop with event-driven waiting, removing ten idle wakeups per second.
- Avoided eager payload hex formatting and other DEBUG-only work when DEBUG logging is disabled.
- Added direct MQTT v5 `UserProperty` access on the common path instead of constructing a full JSON representation.

## Home Assistant behavior

- Power entities whose Home Assistant metadata is exactly `device_class: power` with unit `W` are published as whole watts. Decimal watt values are rounded at the Home Assistant publish boundary, so values near zero such as `-0.4 W` become integer `0 W` instead of appearing as `-0 W`.
- The whole-watt normalization does not modify raw Growatt register decoding and does not affect energy counters in `Wh`/`kWh`, voltage, current, SOC, temperature or other non-power measurements.
- Preserves stable MQTT device identity and rejects placeholder serial values made only of `X` characters from replacing that identity.
- Restores persisted device configuration by MQTT device ID and hardens device metadata publication.
- Keeps the optional Online state retained and invalidates discovery/availability caches after reconnect so retained state can be recreated after broker restarts.
- Removes the manual `Sync Time` button and the exposed `System Time` config entity.
- Automatically synchronizes supported device clocks at 00:00 and 12:00 local time using config register 31.
- Derives time-sync support from the active register map; RAQ/ShineWeLink gateways are not written directly, while a detected PTQ inverter is handled as NEO.
- Inherits the Home Assistant Supervisor timezone when the add-on `TZ` option is empty; an explicitly configured `TZ` remains an override.
- Keeps `MAX_BAT=auto` conservative when the actual battery count is unknown and retains optional battery-position tracking.

## NOAH-specific differences

- Adds validation and documentation based on real NOAH 2000 captures, including a three-module stack.
- Adds passive parsing/diagnostics for the embedded NOAH `0x0103` holding-register block covering `R250-R374`.
- Keeps NOAH Battery Health / SOH as a whole-number percentage.
- Removes the experimental NOAH Home Assistant entities `Temperature PV1`, `Temperature PV2`, `System Temperature` and `MQTT IP` from the effective NOAH map.
- Preserves the existing `Heater` entity but, for NOAH `0PVP` status message `0x0104`, overrides its state from the validated status-frame heater byte at absolute offset 108 when the value is in the existing `0..15` bitmask range.
- Keeps the previous register-derived Heater value as fallback when the status packet/value is unsupported.
- Skips the extra Heater-specific descramble for packets that are too short to contain the validated Heater byte.
- Keeps passive watch logging for unknown NOAH register values without adding active scans or unsafe writes.

## Protocol, safety and persistence hardening

- Adds stricter validation for malformed/truncated Modbus and config traffic, including message lengths, register ranges, trailers and numeric value sizes.
- Accepts valid final single-register blocks and supported protocol trailer bytes correctly.
- Rejects invalid `TIME_HHMM` values instead of publishing malformed times.
- Validates config-write device IDs, register numbers, ASCII values and protocol length limits before building packets.
- Avoids logging config values that can contain credentials.
- Writes persisted device configuration atomically and excludes sensitive password/raw fields.
- Clarifies Growatt Cloud enable/filter behavior and keeps cloud configuration filtering in the Growatt Cloud -> local device direction.
- Checks local MQTT publish results and keeps forwarding clients instance-local with explicit shutdown cleanup.
- Retains the compatibility-oriented TLS behavior rather than imposing stricter certificate verification that could break existing installations.

## Diagnostics

- Adds passive register diagnostics written to `/share/GroBro/register_debug/registers.jsonl`.
- Adds raw MQTT capture to one append-only `/share/GroBro/dump/messages.jsonl` file with exact Base64 payload preservation instead of creating large numbers of individual binary files.
- Optimizes change-only register diagnostics by rejecting unchanged Modbus blocks before per-register unpacking and JSON construction.
- Sets normal-operation diagnostics to low-overhead defaults: `LOG_LEVEL=ERROR`, `DUMP_MESSAGES=false`, `REGISTER_DEBUG=false`.
- Diagnostics remain opt-in and passive; they do not actively scan the configured register range.

## Add-on and runtime integration

- Stores persistent `config_*.json` state under `/data/GroBro` across add-on rebuilds.
- Exports Home Assistant add-on options with shell-safe quoting.
- Keeps application code explicitly on `PYTHONPATH` while runtime state remains in the persistent data directory.
- Includes fork-specific German and English add-on configuration/translation updates.

## CI and container pipeline

- Enables fork CI with Ruff and the full pytest suite on Python 3.11, 3.12 and 3.13 with the configured coverage requirement.
- Adds CI concurrency so superseded runs on the same branch are cancelled.
- Publishes fork container images to `ghcr.io/criticallimit/grobro` instead of the upstream namespace.
- Builds multi-architecture images for `linux/amd64`, `linux/arm64` and `linux/arm/v7`.
- Forces Docker Buildx to use `context: .` after checking out the exact successful CI `head_sha`, so the image is built from the same commit that CI tested.
- The corrected workflow was validated by a successful multi-architecture push whose build metadata records the local context and the exact checked-out revision.

## Additional validation and documentation

- Adds `FORK_CHANGES.md` as the detailed fork-vs-upstream comparison.
- Adds `NOAH_VALIDATION.md` for NOAH capture evidence and validated register findings.
- Adds `REGISTER_DEBUG.md` for passive diagnostics behavior.
- Adds regression coverage for device-family resolution, malformed protocol handling, config persistence/security, discovery/availability caching, reconnect behavior, automatic clock sync, NOAH Heater handling, embedded `0x0103` parsing, register diagnostics, Home Assistant telemetry performance rules and whole-watt power publication including negative-zero elimination.

Existing Home Assistant entity IDs, unique IDs, MQTT state topics, device identifiers and protocol write limits are kept stable wherever possible; the performance changes above are intended to reduce CPU/allocation/idle overhead without changing the supported control semantics.
