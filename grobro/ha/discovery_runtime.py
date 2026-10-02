"""Home Assistant discovery cleanup, migration repair and cache handling."""

from __future__ import annotations

import copy
import ipaddress

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.ha.localization import runtime_language, translate_entity_name

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


def _is_upstream_neo_inverter_power(device_id: str, component_id: str) -> bool:
    return model.is_family(device_id, "neo") and component_id == (
        f"grobro_{device_id}_cmd_inverter_power"
    )


def clean_discovery_payload(client, device_id: str, data: dict) -> dict:
    """Apply Better GroBro cleanup without touching NEO Inverter Power."""
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
        components.pop(f"grobro_{device_id}_cmd_system_time", None)

        language = runtime_language()
        for component_id, component in components.items():
            if not isinstance(component, dict):
                continue
            if isinstance(component.get("name"), str):
                component["name"] = translate_entity_name(
                    component["name"],
                    language,
                )
            # Keep the NEO Inverter Power component structurally identical to
            # Robert's GroBro; only its user-visible name may be localized.
            if _is_upstream_neo_inverter_power(device_id, component_id):
                continue
            component.pop("publish", None)
            component.pop("type", None)
            if component.get("platform") == "sensor":
                component.pop("command_topic", None)
    return data


def build_discovery_repair_payload(device_id: str, clean_data: dict) -> dict:
    """Build an explicit removal update only for unwanted HA components."""
    repair = copy.deepcopy(clean_data)
    components = repair.setdefault("cmps", {})

    components[f"grobro_{device_id}_cmd_mqtt_ip"] = {"platform": "text"}
    components[f"grobro_{device_id}_cmd_system_time"] = {"platform": "text"}
    components[f"grobro_{device_id}_sync_time"] = {"platform": "button"}
    return repair


def clear_legacy_component_discovery(original_publish, device_id: str) -> None:
    """Clear obsolete retained component topics, except NEO Inverter Power."""
    known_registers = model.get_known_registers(device_id)
    if not known_registers:
        return

    base = ha_client_module.HA_BASE_TOPIC
    topics = {f"{base}/number/grobro/{device_id}_set_wirk/config"}

    for name, register in known_registers.holding_registers.items():
        # Robert's working NEO Inverter Power migration/discovery path must remain
        # completely untouched by Better GroBro.
        if model.is_family(device_id, "neo") and name == "inverter_power":
            continue
        component_type = register.homeassistant.type
        topics.add(f"{base}/{component_type}/grobro/{device_id}_{name}/config")
        topics.add(
            f"{base}/{component_type}/grobro/{device_id}_{name}_read/config"
        )

    for name in known_registers.input_registers:
        topics.add(f"{base}/sensor/grobro/{device_id}_{name}/config")

    for topic in sorted(topics):
        original_publish(topic, "", retain=True)
