# Better GroBro

Better GroBro is a Growatt MQTT bridge for Home Assistant, based on [GroBro by Robert Zaage](https://github.com/robertzaage/GroBro).

## Version

**3.0.2**

## What is improved

Compared with the original GroBro, this fork includes:

- improved Home Assistant stability and reconnect behavior
- lower runtime overhead and fewer unnecessary MQTT/discovery updates
- improved Growatt device detection and handling
- improved NOAH support based on validated device captures
- automatic time synchronization for supported devices
- whole-watt Home Assistant power values, avoiding values such as `-0 W`
- additional validation for malformed Growatt protocol messages
- safer persistence of device configuration

The goal is to keep normal GroBro usage simple. Existing GroBro-style configuration remains supported and no additional debug settings are required.

## Installation

Add this repository to the Home Assistant Add-on Store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

## Configuration

Configure the Growatt source MQTT broker and the target Home Assistant MQTT broker as usual.

Most users do not need to change any other options.

## Upstream

Better GroBro is based on GroBro by Robert Zaage and contributors. The original project license remains in [LICENSE](LICENSE).

For developers and troubleshooting, additional technical documentation is available in this repository.
