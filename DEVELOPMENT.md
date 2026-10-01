# Better GroBro developer documentation

Better GroBro is a Home Assistant add-on based on Robert Zaage's GroBro. The project
retains the proven Growatt protocol and register foundation while maintaining its own
Home Assistant runtime, NOAH/NEXA handling, diagnostics and add-on interface.

This document describes the current Better GroBro codebase only. Historical standalone
tools and obsolete setup paths are intentionally not maintained here.

## Runtime entry point

The container starts through:

1. `run.sh`
2. `python -m grobro.ha_bridge`
3. `grobro/ha_bridge.py` installs runtime layers
4. the Growatt-side and Home-Assistant-side MQTT clients are wired together
5. the local Ingress HTTP server is started

Persistent runtime files are stored in `/data/GroBro`.

## Main modules

### Growatt-side protocol

- `grobro/grobro/client.py` — source MQTT, Growatt Cloud forwarding and message routing
- `grobro/grobro/parser.py` — binary/config parsing
- `grobro/grobro/builder.py` — packet construction, scrambling and CRC
- `grobro/grobro/cloud_policy.py` — cloud-forwarding policy
- `grobro/grobro/noah_0103.py` — NOAH/NEO 0x0103 handling
- `grobro/grobro/noah_heater.py` — supported NOAH heater behavior
- `grobro/grobro/raw_dump.py` — optional raw-message diagnostics
- `grobro/grobro/register_debug.py` — optional register diagnostics
- `grobro/grobro/noah_traffic_debug.py` and `noah_protocol_debug.py` — targeted diagnostics
- `grobro/grobro/signals.py` — shutdown signaling

### Home Assistant runtime

- `grobro/ha/client.py` — MQTT discovery, commands and base state handling
- `grobro/ha/performance.py` — state preparation and duplicate-publish suppression
- `grobro/ha/cleanup.py` — installs Better GroBro runtime layers
- `grobro/ha/discovery_runtime.py` — discovery cleanup, migration and metadata
- `grobro/ha/config_runtime.py` — persisted device configuration
- `grobro/ha/timer_runtime.py` — availability/device timers and shutdown cleanup
- `grobro/ha/time_sync_runtime.py` — supported-device clock synchronization
- `grobro/ha/firmware_runtime.py` — firmware composition and discovery invalidation
- `grobro/ha/neo_power_runtime.py` — NEO inverter-power runtime behavior
- `grobro/ha/battery_position.py` — stable/manual battery assignment
- `grobro/ha/device_inventory.py` — detected-device inventory
- `grobro/ha/localization.py` — DE/EN/FR/ES/NL localization
- `grobro/ha/battery_ingress.py` — Better GroBro Ingress UI/API
- `grobro/ha/supervisor_config.py` — Supervisor-backed configuration, restart and log access

### Models and register maps

`grobro/model/` contains device-family detection, typed message/config models and the
JSON register maps for supported Growatt families. Register-map changes should remain
data-driven where possible.

## Runtime installation order

`grobro/ha_bridge.py` installs the runtime layers before creating live clients. This is
intentional: instance state, discovery behavior, timers, performance handling and device
specific compatibility must be in place before MQTT callbacks begin processing traffic.

Avoid adding ad-hoc monkey patches from the entry point. New behavior should live in the
focused runtime module responsible for that concern.

## MQTT flow

### Device to Home Assistant

`Growatt device -> source MQTT -> grobro.Client -> parser -> ha.Client -> target MQTT -> Home Assistant`

The Growatt-side client validates/routes the packet and calls the corresponding
Home-Assistant callback. Better GroBro then prepares the state, updates availability and
publishes only changed values where appropriate.

### Home Assistant to device

`Home Assistant -> target MQTT -> ha.Client -> grobro.Client -> source MQTT -> device`

Commands are built from the current register definition and sent back to the device.

### Growatt Cloud forwarding

Cloud forwarding is optional. Forward clients are per device. A client is not considered
ready until the MQTT CONNACK has been received; code must not publish to a newly created
forward client before that state is confirmed.

Forwarded messages use the `forwarded-for` MQTT user property to prevent echo loops.

## Home Assistant discovery

Better GroBro uses MQTT device discovery. Runtime code is responsible for:

- localized entity display names
- current device metadata
- removal of obsolete components
- dynamic battery/PV discovery where supported
- rebuilding discovery after HA/MQTT reconnects or relevant configuration changes

Entity IDs and MQTT topic identities are compatibility-sensitive. Do not rename them as
part of refactoring unless a migration is implemented and tested.

## Battery identity

For supported NOAH/NEXA data:

- Bat1 is the master
- Bat2/Bat3/Bat4 may be stabilized by serial number
- manual assignments override automatic placement
- persistent maps are written atomically
- all slot-specific values must move together when a battery is remapped

Never infer a new stable identity from incomplete or implausible serial fragments.

## Availability and restarts

Live telemetry, holding-register responses and valid configuration traffic can mark a
device available. Device timeout marks stale devices unavailable without deleting their
entities.

A Home Assistant restart may occur without an MQTT broker reconnect. The Home Assistant
birth topic is therefore also used to reset transient command/discovery state.

## Configuration persistence

Device configuration files are persisted under the runtime directory. Sensitive config
fields are excluded from Better GroBro persistence where applicable.

Add-on options are owned by Supervisor and are changed through the Ingress configuration
API. Configuration saves restart only Better GroBro.

## Testing

The test suite is under `tests/`. CI currently runs the supported Python matrix and
requires at least 85% coverage.

Before a release:

1. ruff must pass
2. the complete pytest suite must pass
3. add-on version metadata must agree across release-facing files
4. container build must succeed
5. the release workflow must complete successfully

Tests should cover behavior, not historical implementation details. When an implementation
is intentionally replaced, update obsolete tests rather than preserving dead code solely
to satisfy them.

## Repository maintenance

Keep the repository focused on the current Home Assistant add-on:

- do not keep superseded standalone scripts alongside authoritative runtime code
- do not duplicate protocol builders/parsers in one-off tools
- remove assets no longer referenced by current documentation
- keep user documentation limited to supported Better GroBro behavior
- preserve upstream attribution and license notices

## Credits

Better GroBro is based on GroBro by Robert Zaage and contributors. The upstream project
remains credited in README and licensing information.
