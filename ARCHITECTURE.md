# Better GroBro architecture

This document describes the fork-specific runtime structure. It is intentionally
technical; the public README remains focused on end-user behavior.

## Design goal

Keep Robert's GroBro protocol and MQTT bridge behavior as the stable core while
isolating Better GroBro hardening, performance work and passive diagnostics into
small, testable modules. This makes upstream merges easier and reduces the risk
that diagnostics affect normal traffic.

## Entrypoint

`grobro/ha_bridge.py` is kept deliberately thin. It is responsible for:

1. configuring logging,
2. installing permanent runtime layers,
3. installing optional diagnostics,
4. loading MQTT configurations,
5. creating the HA and GroBro clients,
6. wiring their callbacks,
7. running the shared lifecycle until shutdown.

## Permanent runtime layers

`grobro/grobro/runtime.py` installs permanent Better GroBro behavior in a fixed,
tested order:

1. GroBro compatibility/runtime cleanup,
2. Home Assistant cleanup/compatibility,
3. Home Assistant telemetry performance layer,
4. system-time entity cleanup.

These layers are considered product behavior rather than reverse-engineering
diagnostics.

## Optional diagnostics

`grobro/grobro/diagnostics.py` is the single bootstrap point for optional passive
diagnostics. It currently installs:

- passive register debugging,
- full passive NOAH MQTT traffic capture.

Diagnostics observe traffic already passing through GroBro. They must not create
additional device reads/writes or alter forwarding semantics.

Raw traffic remains authoritative. Additional decoded fields are annotations only;
raw and descrambled packet data are retained so speculative interpretations cannot
destroy evidence.

## Configuration

`grobro/grobro/configuration.py` owns construction of the three MQTT configs while
preserving the established relationships:

- SOURCE defaults to localhost:1883,
- TARGET defaults to SOURCE,
- FORWARD defaults to mqtt.growatt.com:7006.

`ha_bridge.py` keeps the historical module-level config names for compatibility.

## Device-family registry

`grobro/model/device_family.py` is the single source of truth for Growatt device
serial prefixes, display names, register maps and family capabilities. Both the
GroBro MQTT client and Home Assistant client delegate register-map and device-name
selection to this registry instead of maintaining separate prefix lists.

The registry exposes stable helpers through `grobro.model`, including family
resolution, known-device detection, gateway detection, time-sync capability and
dynamic-PV capability. New runtime code should use these helpers rather than add
new `startswith(...)` device-family tables.

## Growatt cloud forwarding policy

`grobro/grobro/cloud_policy.py` owns parsing and decisions for Growatt cloud
forwarding. It covers:

- disabled values,
- unrestricted forwarding,
- comma-separated device allowlists,
- optional blocking of cloud configuration commands.

The historical `GROWATT_CLOUD*` module variables in `grobro/grobro/client.py` are
retained for compatibility. Runtime decisions are resolved through
`CloudForwardingPolicy`, including when those compatibility variables are patched
by tests or integrations.

## Client wiring

`grobro/grobro/wiring.py` owns the bidirectional callback connections between the
GroBro client and the Home Assistant client. Keeping this in one place makes
client API changes easier to review during upstream merges.

## Lifecycle and signals

`grobro/grobro/lifecycle.py` owns start/wait/stop ordering and guarantees both
clients are stopped when shutdown waiting raises.

`grobro/grobro/signals.py` owns SIGINT/SIGTERM handling.

## NOAH reverse engineering rules

- Do not expose speculative registers as Home Assistant entities.
- Do not mark a register writable unless writing is independently validated.
- Prefer passive observation over active probing.
- Preserve complete MQTT traffic during investigation.
- Treat the normal R0-R124 telemetry, embedded R250-R374 block, 0x0105/0x0106
  single-register control traffic and 0x0118/0x0119 config traffic as distinct
  protocol surfaces.
- Current evidence does not establish per-module NOAH charge/discharge current or
  power in MQTT telemetry.

## Merge strategy

When syncing with upstream Robert GroBro:

1. preserve upstream protocol/parser fixes unless they conflict with validated fork
   behavior,
2. keep fork-specific runtime/bootstrap modules separate where possible,
3. re-run the full CI matrix after every merge,
4. keep diagnostics passive and optional,
5. update `FORK_CHANGES.md` when behavior relative to upstream changes.
