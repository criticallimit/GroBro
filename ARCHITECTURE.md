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

1. centralized raw MQTT dump compatibility hook,
2. validated NOAH heater compatibility hook,
3. Home Assistant cleanup/compatibility,
4. Home Assistant telemetry performance layer,
5. system-time entity cleanup.

The GroBro-side runtime no longer enters through one broad cleanup hook. The two
remaining GroBro monkey patches are deliberately isolated in focused modules with
separate tests:

- `grobro/grobro/raw_dump_hook.py`
- `grobro/grobro/noah_heater_hook.py`

`grobro/grobro/cleanup.py` is retained only as a compatibility bootstrap for older
imports/extensions. It is not part of the normal runtime installation path.

These layers are considered product behavior rather than reverse-engineering
diagnostics.

## Home Assistant compatibility runtime

`grobro/ha/cleanup.py` is now a thin, idempotent compatibility bootstrap rather
than a monolithic implementation. It keeps historical helper names as aliases for
older tests/extensions while installing focused modules in a stable order:

- `battery_runtime.py` — family registry, cached battery-key parsing and MAX_BAT resolution,
- `state_runtime.py` / `runtime_state.py` — per-client mutable runtime state,
- `config_runtime.py` — config restore/persistence and sensitive-field cleanup,
- `time_sync_runtime.py` — automatic 00:00/12:00 clock synchronization,
- `pv_runtime.py` — dynamic PV-count capability gating,
- `availability_runtime.py` / `availability.py` — retained availability and reconnect invalidation,
- `timer_runtime.py` / `timers.py` — device timeout and shutdown timer lifecycle,
- `discovery_runtime.py` — discovery cleanup, identity normalization and discovery caching.

The bootstrap order is regression-tested. New HA compatibility behavior should be
added to the narrowest applicable module instead of growing `ha/cleanup.py` again.

## Raw MQTT dumps

`grobro/grobro/raw_dump.py` owns the actual append-only raw MQTT dump implementation.
It writes one `messages.jsonl` stream and preserves payload bytes losslessly as
Base64. The compatibility hook only redirects the historical
`dump_message_binary(...)` entry point to this centralized implementation.

The dump code itself must not parse, filter or mutate traffic.

## NOAH heater compatibility

`grobro/grobro/noah_heater.py` contains the packet interpretation for the validated
NOAH heater byte. `grobro/grobro/noah_heater_hook.py` contains only the runtime
attachment logic that temporarily augments the HA input callback and restores the
original callback afterwards.

Keeping interpretation and hook installation separate makes the empirical NOAH
behavior testable without coupling it to MQTT client patching.

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
resolution, known-device detection, gateway detection, time-sync capability,
dynamic-PV capability and NOAH-protocol capability. New runtime code should use
these helpers rather than add new `startswith(...)` device-family tables.

## Growatt config packet builders

`grobro/grobro/builder.py` owns construction of Growatt config read/write packets,
including `0x0119` reads and `0x0118` writes. The MQTT client calls these builders
instead of assembling packet headers, TLVs, lengths, scrambling and CRC locally.

Input validation for device IDs, register numbers and ASCII config values belongs
in the builders so packet safety has one implementation and one test surface.

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

## Home Assistant telemetry publication

`grobro/ha/performance.py` owns the low-risk HA telemetry hot path. It applies the
existing value rules in one pass, including ENUM conversion, battery filtering,
whole-watt power normalization and optional total-increasing glitch protection.

The performance layer also keeps a per-device cache of the exact JSON state last
published to Home Assistant. A fully identical state is not republished. Any real
change is published immediately, including transitions such as
`500 -> 501 -> 500`. This removes redundant MQTT churn without discarding actual
measurement changes or breaking Home Assistant history/energy integration.

The state cache is cleared on MQTT reconnect so the next live state is always
published after a broker/session interruption.

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
