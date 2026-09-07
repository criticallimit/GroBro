"""Home Assistant discovery cleanup, migration repair and cache handling."""

from __future__ import annotations

import copy
import ipaddress
import json

import grobro.model as model
from grobro.ha import client as ha_client_module

FORK_URL = "https://github.com/criticallimit/GroBro"


def configured_serial(client, device_id: str) -> str:
    config = getattr(client, "_config_cache", {}).get(device_id)
    serial = getattr(config, "serial_number", None) if config else None
    if serial and str(serial).strip():
        return str(serial).strip()
    return device_id


def configured_local_ip(client, device_id: str) -> str | None:
    config = getattr(client, "_config_cache", {}).get(device_id)
    value = getattr(config, "local_ip", None) if config else None
    if not value:
        return None

    text = str(value).strip().strip("\x00")
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if address.is_unspecified:
        return None
    return str(address)


def configuration_url_for_ip(ip_value: str) -> str:
    address = ipaddress.ip_address(ip_value)
    if address.version == 6:
        return f"http://[{address}]"
    return f"http://{address}"


def clean_discovery_payload(client, device_id: str, data: dict) -> dict:
    """Apply Better GroBro's family-independent HA discovery cleanup."""
    origin = data.get("o")
    if isinstance(origin, dict):
        origin["url"] = FORK_URL

    device_meta = data.get("dev")
    if isinstance(device_meta, dict):
        device_meta["serial_number"] = configured_serial(client, device_id)
        local_ip = configured_local_ip(client, device_id)
        if local_ip:
            device_meta["configuration_url"] = configuration_url_for_ip(local_ip)
        else:
            device_meta.pop("configuration_url", None)

    components = data.get("cmps")
    if isinstance(components, dict):
        # Manual clock controls are hidden for every supported family; automatic
        # time sync remains active internally where the family supports it.
        components.pop(f"grobro_{device_id}_sync_time", None)
        components.pop(f"grobro_{device_id}_cmd_system_time", None)

        for component in components.values():
            if not isinstance(component, dict):
                continue
            component.pop("publish", None)
            component.pop("type", None)
            if component.get("platform") == "sensor":
                component.pop("command_topic", None)
    return data


def build_discovery_repair_payload(device_id: str, clean_data: dict) -> dict:
    """Build one explicit HA device-discovery component removal update.

    Home Assistant device discovery requires a component that is being removed to
    remain in ``cmps`` with only its platform. Omitting it from an update is not a
    reliable deletion signal. For NEO we also remove/re-add Inverter Power once to
    repair stale entity-registry/discovery state left by older migration payloads.
    """
    repair = copy.deepcopy(clean_data)
    components = repair.setdefault("cmps", {})

    components[f"grobro_{device_id}_cmd_mqtt_ip"] = {"platform": "text"}
    components[f"grobro_{device_id}_cmd_system_time"] = {"platform": "text"}
    components[f"grobro_{device_id}_sync_time"] = {"platform": "button"}

    if model.is_family(device_id, "neo"):
        components[f"grobro_{device_id}_cmd_inverter_power"] = {
            "platform": "switch"
        }

    return repair


def clear_legacy_component_discovery(original_publish, device_id: str) -> None:
    """Clear retained single-component discovery topics after migration.

    GroBro's historical migration publishes retained ``migrate_discovery`` markers
    to the old per-component topics. Home Assistant requires those topics to be
    cleared after the device-discovery configuration has been published; otherwise
    the retained migration messages can be replayed after later MQTT/HA restarts.
    """
    known_registers = model.get_known_registers(device_id)
    if not known_registers:
        return

    base = ha_client_module.HA_BASE_TOPIC
    topics = {f"{base}/number/grobro/{device_id}_set_wirk/config"}

    for name, register in known_registers.holding_registers.items():
        component_type = register.homeassistant.type
        topics.add(f"{base}/{component_type}/grobro/{device_id}_{name}/config")
        topics.add(
            f"{base}/{component_type}/grobro/{device_id}_{name}_read/config"
        )

    for name in known_registers.input_registers:
        topics.add(f"{base}/sensor/grobro/{device_id}_{name}/config")

    for topic in sorted(topics):
        original_publish(topic, "", retain=True)


def migration_set(client) -> set:
    migrations = getattr(client, "_migration_done", None)
    if migrations is None:
        migrations = set()
        client._migration_done = migrations
    return migrations


def discovery_signature(
    client, device_id: str, effective_max_bat: int
) -> tuple[int, int | None]:
    pv_count = getattr(client, "_neo_pv_count", {}).get(device_id)
    return effective_max_bat, pv_count


def install_discovery_runtime(resolve_max_bat) -> None:
    client_cls = ha_client_module.Client
    original_migrate = client_cls._Client__migrate_entity_discovery

    def migrate_once(self, device_id, known_registers):
        migrations = migration_set(self)
        if device_id in migrations:
            return
        original_migrate(self, device_id, known_registers)
        migrations.add(device_id)

    client_cls._Client__migrate_entity_discovery = migrate_once
    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_clean(self, device_id: str, effective_max_bat=None):
        if effective_max_bat is None:
            effective_max_bat = resolve_max_bat(device_id)

        signature = discovery_signature(self, device_id, effective_max_bat)
        signatures = getattr(self, "_discovery_signature", None)
        if signatures is None:
            signatures = {}
            self._discovery_signature = signatures
        if device_id in self._discovery_cache and signatures.get(device_id) == signature:
            return None

        original_publish = self._client.publish
        repair_done = getattr(self, "_better_312_discovery_repair_done", None)
        if repair_done is None:
            repair_done = set()
            self._better_312_discovery_repair_done = repair_done

        legacy_cleanup_done = getattr(self, "_legacy_discovery_cleanup_done", None)
        if legacy_cleanup_done is None:
            legacy_cleanup_done = set()
            self._legacy_discovery_cleanup_done = legacy_cleanup_done

        def publish(topic, payload=None, *args, **kwargs):
            is_device_config = (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"
            )
            if is_device_config and payload:
                try:
                    data = json.loads(payload)
                    clean_data = clean_discovery_payload(self, device_id, data)

                    if device_id not in repair_done:
                        repair_payload = json.dumps(
                            build_discovery_repair_payload(device_id, clean_data),
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        original_publish(topic, repair_payload, *args, **kwargs)
                        repair_done.add(device_id)

                    payload = json.dumps(
                        clean_data,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    pass

            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/serial":
                payload = configured_serial(self, device_id)

            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/sw_version":
                config = getattr(self, "_config_cache", {}).get(device_id)
                sw_version = getattr(config, "sw_version", None) if config else None
                if not sw_version:
                    return None
                payload = sw_version

            result = original_publish(topic, payload, *args, **kwargs)

            # The original HA client publishes the final device-discovery payload
            # after any migration markers. Once that final payload has been sent,
            # clear obsolete retained single-component topics and publish the full
            # device config once more as the last retained discovery state.
            if is_device_config and payload and device_id not in legacy_cleanup_done:
                clear_legacy_component_discovery(original_publish, device_id)
                legacy_cleanup_done.add(device_id)
                original_publish(topic, payload, *args, **kwargs)

            return result

        self._client.publish = publish
        try:
            result = original_publish_discovery(self, device_id, effective_max_bat)
            signatures[device_id] = signature
            return result
        finally:
            self._client.publish = original_publish

    client_cls._Client__publish_device_discovery = publish_discovery_clean
