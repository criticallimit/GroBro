# Better GroBro

Better GroBro is a fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro) for Home Assistant.

This README intentionally lists **only the differences from Robert Zaage's GroBro**. Everything not listed here follows the upstream project.

## Better GroBro 3.1.16

Compared with Robert's GroBro, Better GroBro adds:

- **Lower Home Assistant/MQTT churn**: unchanged discovery, availability and identical telemetry states are not republished unnecessarily. Real value changes are still published immediately.
- **Lower telemetry CPU/allocation load**: unchanged prepared Home Assistant states are detected before JSON serialization, avoiding unnecessary `json.dumps()` work and temporary strings.
- **Consistent Home Assistant cleanup across NOAH, NEO and NEXA**: low-level `MQTT IP` is hidden for all three families, while manual `Sync Time` and `System Time` controls are removed in favor of automatic synchronization.
- **Discovery repair for existing installations**: stale retained MQTT discovery/migration topics are explicitly cleaned up during upgrade instead of relying on Home Assistant to infer removal from an omitted component.
- **NEO Inverter Power left on Robert's original path**: Better GroBro no longer removes, re-creates, rewrites or clears discovery data for the NEO `Inverter Power` switch. Its discovery fields, command topic, state topic and migration path remain the same as in Robert's GroBro.
- **Improved NOAH handling**: validated multi-battery telemetry behavior, corrected battery-count handling and a validated NOAH heater-state fallback from the cyclic status packet.
- **Stable NOAH/NEXA battery identities**: with `KEEP_BATTERY_POSITION=true`, battery serial numbers are persistently bound to logical Bat2/Bat3/Bat4 slots. If a stack is re-enumerated after a module drops out, all slot-specific values of that module are remapped together to the original Home Assistant battery instead of Bat2/Bat3 swapping. NEXA module serials are decoded internally and are not exposed as additional HA entities.
- **Automatic clock synchronization** for supported devices at 00:00 and 12:00 local time.
- **Cleaner Home Assistant values**: power sensors in watts are published as whole watts, including removal of `-0 W`, without changing raw register decoding or energy counters.
- **Stronger protocol validation** for malformed/truncated Growatt Modbus and configuration packets.
- **Safer configuration handling**: validated config packet construction, no credential values in normal logs, and sensitive raw/password data excluded from persisted configuration.
- **More robust reconnect/runtime behavior**: cached state is invalidated correctly after reconnect, timers are cleaned up on shutdown, and device configuration is restored by MQTT device ID.
- **Improved Growatt Cloud forwarding controls** with consistent enable/allowlist behavior and optional blocking of cloud configuration commands.
- **Optional passive diagnostics** for register and raw MQTT analysis without active register scanning or additional device writes.
- **Diagnostics removed from the normal hot path**: NOAH traffic-capture wrappers are installed only when `REGISTER_DEBUG=true`, avoiding diagnostic topic handling and duplicate unscrambling in normal operation.
- **Smaller production add-on**: runtime dependencies are separated from test/lint tooling, so the Home Assistant image no longer installs pytest, coverage, pylint or rope.
- **Lower MQTT startup overhead**: the unchanged Home Assistant command topic set is subscribed in one MQTT SUBSCRIBE operation instead of twelve separate calls.
- **Lower holding-state MQTT churn**: unchanged switch/number/time/select register states are not republished repeatedly; reconnect clears the cache so Home Assistant receives fresh state again.
- **Less repeated discovery work**: identical device configuration packets no longer rebuild Home Assistant discovery after the device is already discovered; real config changes still invalidate and republish discovery.
- **Single config restore pass**: persisted device configs are loaded once at startup and remain keyed by the MQTT device ID from the filename, including gateway/inverter combinations.
- **Runtime performance improvements** that reduce repeated parsing, allocations and idle work while preserving supported GroBro behavior.

## Installation

Add this repository to the Home Assistant add-on store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

The add-on keeps the existing GroBro-compatible configuration and add-on slug so existing installations can update in place.

## Upstream

Base project: [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.

Upstream comparison baseline for Better GroBro 3.1.16: `e4d59b20ba472853ae6ec0b7a17cf15cd774cb23`.

See [CHANGELOG.md](CHANGELOG.md) for the technical list of Better GroBro differences.

The original project license remains in [LICENSE](LICENSE).
