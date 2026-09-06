"""Home Assistant discovery cleanup and cache handling."""

from __future__ import annotations

import ipaddress
import json

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
        components.pop(f"grobro_{device_id}_sync_time", None)
        for component in components.values():
            if not isinstance(component, dict):
                continue
            component.pop("publish", None)
            component.pop("type", None)
            if component.get("platform") == "sensor":
                component.pop("command_topic", None)
    return data


def migration_set(client) -> set:
    migrations = getattr(client, "_migration_done", None)
    if migrations is None:
        migrations = set()
        client._migration_done = migrations
    return migrations


def discovery_signature(client, device_id: str, effective_max_bat: int) -> tuple[int, int | None]:
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

        def publish(topic, payload=None, *args, **kwargs):
            if topic == f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config" and payload:
                try:
                    data = json.loads(payload)
                    payload = json.dumps(
                        clean_discovery_payload(self, device_id, data),
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

            return original_publish(topic, payload, *args, **kwargs)

        self._client.publish = publish
        try:
            result = original_publish_discovery(self, device_id, effective_max_bat)
            signatures[device_id] = signature
            return result
        finally:
            self._client.publish = original_publish

    client_cls._Client__publish_device_discovery = publish_discovery_clean
