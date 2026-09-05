# GroBro Register Debug

> Debug fork of [robertzaage/GroBro](https://github.com/robertzaage/GroBro) for passive Growatt register discovery in Home Assistant. The upstream project remains the source for normal GroBro development and releases.

GroBro is a bridge service that decodes encrypted MQTT packets from Growatt NEO, NOAH, NEXA, SPF (Shine WiFi-X), TL-XH2 and ShineWeLink-X2 devices and republishes them in a format compatible with Home Assistant.

This fork keeps the normal GroBro behavior and adds a passive register capture mode. It does **not** actively scan devices and does **not** send additional register read/write commands.

## Debug additions

- Passive capture of successfully parsed Modbus register blocks.
- Captures confirmed register numbers from `0` through the configured maximum (`3000` by default).
- Stores uint16, int16, hex, high byte, low byte, previous value and change state.
- Captures the first observation of every register even when `REGISTER_DEBUG_CHANGES_ONLY` is enabled.
- Records special NOAH/NEXA `0x0103` payload values separately as indexes when their real start address is not known.
- Writes the JSONL capture to `/share/GroBro/register_debug/registers.jsonl`.

See [REGISTER_DEBUG.md](REGISTER_DEBUG.md) for details.

## Installation as Home Assistant app/add-on

Use this fork as the repository:

[![Open your Home Assistant instance and add the GroBro Register Debug repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcriticallimit%2FGroBro)

Or add this repository manually in the Home Assistant app/add-on store:

`https://github.com/criticallimit/GroBro`

Then refresh the store and install **GroBro Register Debug**.

Do not run the upstream GroBro add-on and this debug add-on against the same Growatt MQTT source at the same time unless you deliberately configured separate MQTT client identities and understand the consequences. For a normal capture, stop the upstream GroBro add-on first and run this debug build instead.

## Default debug settings

```yaml
REGISTER_DEBUG: true
REGISTER_DEBUG_DIR: /share/GroBro/register_debug
REGISTER_DEBUG_MAX_REGISTER: 3000
REGISTER_DEBUG_CHANGES_ONLY: true
```

`REGISTER_DEBUG_MAX_REGISTER=3000` is only a capture filter. It does not cause GroBro to query registers 0-3000. Registers are captured only when the device actually sends them in a message that GroBro can parse.

## Normal GroBro setup

The underlying MQTT/TLS setup is unchanged from upstream GroBro. For the full setup, certificates and device configuration documentation, use the upstream project documentation:

- [GroBro upstream](https://github.com/robertzaage/GroBro)
- [Configuration guide](https://github.com/robertzaage/GroBro/blob/main/CONFIGURATION.md)
- [Certificates guide](https://github.com/robertzaage/GroBro/blob/main/CERTIFICATES.md)

## License and upstream attribution

This repository is a fork of GroBro by Robert Zaage and contributors. The original project license remains in [LICENSE](LICENSE).
