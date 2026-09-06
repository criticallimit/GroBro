# Better GroBro

Better GroBro is a fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro) for Home Assistant.

This README intentionally lists **only the differences from Robert Zaage's GroBro**. Everything not listed here follows the upstream project.

## Better GroBro 3.1.0

Compared with Robert's GroBro, Better GroBro adds:

- **Lower Home Assistant/MQTT churn**: unchanged discovery, availability and identical telemetry states are not republished unnecessarily. Real value changes are still published immediately.
- **Improved NOAH handling**: validated multi-battery telemetry behavior, corrected battery-count handling and a validated NOAH heater-state fallback from the cyclic status packet.
- **Automatic clock synchronization** for supported devices at 00:00 and 12:00 local time; the manual Sync Time entity/button is removed.
- **Cleaner Home Assistant values**: power sensors in watts are published as whole watts, including removal of `-0 W`, without changing raw register decoding or energy counters.
- **Stronger protocol validation** for malformed/truncated Growatt Modbus and configuration packets.
- **Safer configuration handling**: validated config packet construction, no credential values in normal logs, and sensitive raw/password data excluded from persisted configuration.
- **More robust reconnect/runtime behavior**: cached state is invalidated correctly after reconnect, timers are cleaned up on shutdown, and device configuration is restored by MQTT device ID.
- **Improved Growatt Cloud forwarding controls** with consistent enable/allowlist behavior and optional blocking of cloud configuration commands.
- **Optional passive diagnostics** for register and raw MQTT analysis without active register scanning or additional device writes.
- **Runtime performance improvements** that reduce repeated parsing, allocations and idle work while preserving supported GroBro behavior.

## Installation

Add this repository to the Home Assistant add-on store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

The add-on keeps the existing GroBro-compatible configuration and add-on slug so existing installations can update in place.

## Upstream

Base project: [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.

Upstream comparison baseline for Better GroBro 3.1.0: `4797f8419bd574bcebd32d1a859569f97b58b774`.

See [CHANGELOG.md](CHANGELOG.md) for the technical list of Better GroBro differences.

The original project license remains in [LICENSE](LICENSE).
