# Better GroBro

Growatt MQTT Message Broker for Home Assistant.

This repository is based on GroBro by Robert Zaage and contains additional stability, performance, Home Assistant and NOAH improvements.

## Current release

**3.0.2**

> Version 3.0.3 was withdrawn because of a malformed Home Assistant add-on configuration. Do not install 3.0.3.

## Improvements compared with the original GroBro

- Improved stability and runtime efficiency.
- More robust Home Assistant discovery and reconnect handling.
- Improved device detection and persistence.
- Improved NOAH support based on validated device captures.
- Automatic time synchronization for supported devices.
- Power sensors in watts are published as whole numbers.
- Additional validation for malformed Growatt communication.
- Optional passive diagnostics for troubleshooting and protocol analysis.

## Installation

Add this repository to the Home Assistant add-on store:

`https://github.com/criticallimit/GroBro`

Then install or update **Better GroBro**.

Existing GroBro configuration can continue to be used.

## Upstream

Better GroBro is based on [robertzaage/GroBro](https://github.com/robertzaage/GroBro) by Robert Zaage and contributors.

The original project license remains in [LICENSE](LICENSE).
