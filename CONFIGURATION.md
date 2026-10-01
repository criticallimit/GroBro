# Better GroBro configuration

Better GroBro is configured from the built-in Home Assistant add-on interface. The
Ingress page provides configuration, detected-device information, battery assignment,
diagnostics and the current-process log.

The add-on reads its settings from Home Assistant Supervisor. Saving configuration in
the Better GroBro interface restarts only the Better GroBro add-on so the new values are
loaded consistently.

## MQTT

| Option | Default | Purpose |
|---|---|---|
| `SOURCE_MQTT_HOST` | `homeassistant.local` | MQTT broker receiving Growatt device traffic |
| `SOURCE_MQTT_PORT` | `7006` | Source MQTT port |
| `SOURCE_MQTT_TLS` | `true` | Enable TLS for the source connection |
| `SOURCE_MQTT_USER` | empty | Optional source MQTT username |
| `SOURCE_MQTT_PASS` | empty | Optional source MQTT password |
| `TARGET_MQTT_HOST` | `homeassistant.local` | Home Assistant MQTT broker |
| `TARGET_MQTT_PORT` | `1883` | Target MQTT port |
| `TARGET_MQTT_TLS` | `false` | Enable TLS for the target connection |
| `TARGET_MQTT_USER` | empty | Optional target MQTT username |
| `TARGET_MQTT_PASS` | empty | Optional target MQTT password |
| `MQTT_CLIENT_SUFFIX` | empty | Optional suffix when multiple Better GroBro instances share a broker |
| `HA_BASE_TOPIC` | `homeassistant` | Home Assistant MQTT discovery prefix |

## Growatt Cloud forwarding

| Option | Default | Purpose |
|---|---|---|
| `GROWATT_CLOUD` | `false` | Forward supported traffic between the local broker and Growatt Cloud |
| `GROWATT_CLOUD_CONFIG_FILTER` | `false` | Block cloud-originated configuration/control traffic while allowing telemetry forwarding |

Cloud forwarding is optional. Local Home Assistant operation does not require it.

## Device and Home Assistant behavior

| Option | Default | Purpose |
|---|---|---|
| `DEVICE_TIMEOUT` | `120` | Minimum inactivity time in seconds before a device becomes unavailable |
| `MAX_SLOTS` | `1` | Maximum number of schedule slots exposed where supported |
| `MAX_BAT` | `auto` | Battery count; `auto` uses detected/device-reported information |
| `AVAILABILITY_SENSOR` | `false` | Also expose a dedicated availability binary sensor |
| `KEEP_BATTERY_POSITION` | `false` | Keep supported battery modules on stable logical slots by serial number |
| `TZ` | empty | Optional timezone override; otherwise the Home Assistant timezone is used |

### Battery assignment

For supported NOAH/NEXA layouts, Better GroBro can keep battery identities stable even
when the device changes its physical enumeration. Manual Bat2/Bat3/Bat4 assignments can
be configured from the Batteries page. Bat1 is the master and is not manually reordered.

## Logging and diagnostics

| Option | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `ERROR` | `ERROR`, `INFO` or `DEBUG` |
| `DUMP_MESSAGES` | `false` | Enable raw-message diagnostics |
| `DUMP_DIR` | `/share/GroBro/dump` | Raw-message diagnostic output directory |
| `REGISTER_DEBUG` | `false` | Enable register diagnostics |
| `REGISTER_DEBUG_DIR` | `/share/GroBro/register_debug` | Register diagnostic output directory |
| `REGISTER_DEBUG_MAX_REGISTER` | `65535` | Highest register considered by register diagnostics |
| `REGISTER_DEBUG_CHANGES_ONLY` | `true` | Record only changed register values where applicable |

Diagnostics are intended for troubleshooting and can generate substantial data. Leave
them disabled for normal operation.

## Persistent runtime data

Better GroBro stores its runtime state under `/data/GroBro`, including persisted device
configuration and battery-position information. These files survive normal add-on
updates/rebuilds.

Diagnostic output under `/share/GroBro` is separate from the runtime state.

## Updating

Install and update Better GroBro from the Home Assistant Add-on Store using:

`https://github.com/criticallimit/GroBro`

Existing supported settings are retained during normal in-place updates.
