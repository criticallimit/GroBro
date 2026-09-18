# Better GroBro 3.1.18 — Changes compared with robertzaage/GroBro

This changelog intentionally lists **only the material differences from Robert Zaage's GroBro**. It is not a historical release log.

Comparison baseline:

- Upstream: `robertzaage/GroBro`
- Upstream `main`: `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23`
- Comparison date: 2026-09-18

## Home Assistant

- Suppresses repeated publication of an identical complete telemetry state while preserving every real value change.
- Caches unchanged discovery and availability publications to reduce MQTT and Home Assistant churn.
- Clears state/discovery/availability caches after reconnect so fresh live state is republished.
- Publishes power sensors whose HA metadata is `device_class: power` and unit `W` as whole watts; raw Growatt decoding and energy counters remain unchanged.
- Removes negative-zero presentation such as `-0 W`.
- Uses conservative automatic battery-count handling instead of assuming the maximum battery count when unknown.
- Keeps Home Assistant device identity stable and avoids replacing it with invalid placeholder serials.
- Hides the low-level `MQTT IP` configuration entity consistently for NOAH, NEO and NEXA.
- Removes the manual `Sync Time` button and exposed `System Time` entity consistently in the actual final discovery path.
- Repairs existing retained MQTT discovery state during upgrade: obsolete component-discovery migration topics are explicitly cleared after the new device-based discovery is established.
- Uses Home Assistant's explicit component-removal update for stale `MQTT IP`, `System Time` and `Sync Time` components instead of only omitting them from later discovery payloads.
- Leaves the NEO `Inverter Power` switch on Robert's original GroBro path. Better GroBro does not remove/re-add it, does not strip its upstream discovery fields, and does not clear its legacy discovery topics. The final component retains Robert's `publish`, `type`, platform, command topic and state topic unchanged.

## NOAH / NEXA

- Adds hardware-validated handling for NOAH multi-battery telemetry and battery count.
- Preserves the existing Heater entity but can use the validated heater byte from NOAH `0x0104` cyclic status traffic when available; unsupported packets fall back to the existing register-derived state.
- Adds passive decoding/observation support for NOAH holding/config traffic used during validation without active register scanning.
- Removes fork-tested NOAH entities that were not useful/reliable enough for normal Home Assistant presentation: `Temperature PV1`, `Temperature PV2` and `System Temperature`.
- Keeps NOAH-only removals NOAH-specific; NEO/NEXA telemetry is not removed without family-specific validation.
- Extends Robert's `KEEP_BATTERY_POSITION` behavior from warning-only detection to actual serial-based slot stabilization for NOAH and NEXA: Bat2/Bat3/Bat4 telemetry is remapped to persistent logical positions when the stack is re-enumerated.
- Persists NOAH/NEXA serial-to-slot assignments in `battery_positions.json` so stable battery identities survive add-on/Home Assistant restarts.
- Reserves absent battery slots so a remaining or newly seen module cannot silently steal the logical identity of a temporarily missing battery.
- Decodes NEXA Bat2/Bat3/Bat4 module serial fragments internally at registers 33–39, 45–51 and 57–63 with `publish:false`; no additional serial entities are added to Home Assistant.
- Remaps all recognized slot-specific values together (for example NEXA `battery2Soc`/`battery3Soc`) so one module's values cannot be split across different logical batteries.
- Prefers NEXA's own `batteryPackageQuantity` for automatic battery-count detection before falling back to serial fragments.

## Time synchronization

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
- Skips JSON serialization for unchanged prepared Home Assistant telemetry states.
- Installs NOAH full-traffic diagnostic wrappers only when `REGISTER_DEBUG=true`, avoiding duplicate unscrambling and diagnostic hot-path work during normal operation.
- Avoids DEBUG-only payload formatting work unless DEBUG logging is enabled.
- Uses direct MQTT v5 `UserProperty` access on the common path.
- Uses event-driven shutdown waiting instead of a 100 ms polling loop.
- Uses daemon helper timers with explicit cleanup and lower timeout timer churn.
- Restores persisted device configuration by MQTT device ID.
- Batches the unchanged Home Assistant command subscriptions into one MQTT SUBSCRIBE operation instead of twelve separate subscribe calls.
- Suppresses repeated unchanged holding-register state publishes while clearing the cache on reconnect so fresh state is sent again.
- Avoids rebuilding Home Assistant discovery for identical repeated device configuration packets once the device is already discovered.
- Restores persisted device configuration in one startup pass, keyed by MQTT device ID from the config filename.
- Uses the shared NOAH/NEXA protocol capability for common runtime behavior instead of duplicated family checks.
- Caches static firmware-part ordering per device/register layout to avoid repeated key scans, list allocation and sorting on every telemetry frame.
- Suppresses repeated identical NOAH/NEXA Smart Meter `0x6F64` state publications and clears that cache after MQTT reconnect.
- Prevents overlapping `Read All Values` cycles per device so repeated button presses cannot duplicate Modbus/config reads or helper timers.
- Releases the Read All guard after normal completion, timeout or config-read callback failure.\n- Consolidates fourteen small bootstrap/runtime wrapper modules into their owning implementation modules or `ha_bridge.py`; behavior and installation order are preserved while reducing import depth and monkey-patch indirection.

## Optional diagnostics

- Adds passive register diagnostics under `/share/GroBro/register_debug/`.
- Adds an append-only raw MQTT JSONL capture under `/share/GroBro/dump/messages.jsonl` with lossless Base64 payload storage.
- Diagnostics are opt-in and passive: they do not create extra register scans or device writes.

## Add-on / CI

- Uses the Better GroBro add-on name while retaining the existing add-on slug for in-place updates.
- Persists runtime configuration data under the add-on data directory.
- Adds fork CI on Python 3.11, 3.12 and 3.13 with Ruff, pytest and coverage checks.
- Separates runtime dependencies from development/test tooling so production images install only required runtime Python packages.
- Keeps pytest, coverage, pylint, rope and Ruff available through `requirements-dev.txt` for CI/development without shipping them in the add-on image.
- Publishes Better GroBro container builds through the fork's own GHCR pipeline.

All other functionality is inherited from Robert Zaage's GroBro and is intentionally not duplicated in this changelog.
