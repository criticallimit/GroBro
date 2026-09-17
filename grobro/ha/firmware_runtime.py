"""Combined NOAH/NEXA firmware composition for Home Assistant.

Growatt exposes storage/inverter firmware in ``fw_version_part_*`` input
registers while the datalogger firmware is already available as
``DeviceConfig.sw_version``. ShinePhone displays those values as one version,
for example::

    NOAH: 19.19.14 + 4.0.1.9 -> 19.19.14.4019
    NEXA: 14.12.14.11 + 4.0.1.9 -> 14.12.14.11.4019

This runtime layer keeps the existing Home Assistant ``Firmware Version``
entity and also updates the device-info ``Firmware`` field to the same composed
version. No firmware value is hard-coded.
"""

from __future__ import annotations

import json
import logging

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.model.growatt_registers import HomeAssistantInputRegister

LOG = logging.getLogger(__name__)
_INSTALLED = False


def _supports_combined_firmware(device_id: str) -> bool:
    """Return whether this device family exposes firmware in multiple parts."""
    return model.is_family(device_id, "noah") or model.is_family(device_id, "nexa")


def _compact_datalogger_version(value: object) -> str | None:
    """Convert a dotted numeric datalogger version to the ShinePhone suffix."""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    parts = text.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        return None

    return "".join(parts)


def _firmware_part_names(payload: dict) -> list[str]:
    """Return firmware part keys in numeric part order."""
    names = [name for name in payload if name.startswith("fw_version_part_")]

    def part_number(name: str) -> int:
        try:
            return int(name.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            return 9999

    return sorted(names, key=part_number)


def compose_combined_firmware(payload: dict, datalogger_version: object) -> str | None:
    """Build the ShinePhone-style firmware version from live values."""
    names = _firmware_part_names(payload)
    if not names:
        return None

    base_parts: list[str] = []
    for name in names:
        value = payload.get(name)
        if value is None or str(value).strip() == "":
            return None
        base_parts.append(str(value).strip())

    base_version = ".".join(base_parts)
    suffix = _compact_datalogger_version(datalogger_version)
    if suffix:
        return f"{base_version}.{suffix}"
    return base_version


# Backwards-compatible name for existing callers.
compose_noah_firmware = compose_combined_firmware


def _rewrite_firmware_discovery(
    device_id: str,
    payload: object,
    firmware_version: str | None,
) -> object:
    """Use the composed firmware for both the sensor and HA device metadata."""
    if not payload or not isinstance(payload, (str, bytes, bytearray)):
        return payload

    try:
        raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
        data = json.loads(raw)
    except (UnicodeDecodeError, TypeError, ValueError):
        return payload

    components = data.get("cmps")
    if isinstance(components, dict):
        component = components.get(f"grobro_{device_id}_fw_version")
        if isinstance(component, dict):
            component["value_template"] = "{{ value_json['fw_version'] }}"

    if firmware_version:
        device_info = data.get("dev")
        if isinstance(device_info, dict):
            device_info["sw_version"] = firmware_version

    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _invalidate_discovery_for_firmware_change(client, device_id: str) -> None:
    """Force HA discovery to be republished when the composed firmware changes."""
    discovery_cache = getattr(client, "_discovery_cache", None)
    if isinstance(discovery_cache, list) and device_id in discovery_cache:
        discovery_cache.remove(device_id)

    discovery_payload_cache = getattr(client, "_discovery_payload_cache", None)
    if isinstance(discovery_payload_cache, dict):
        discovery_payload_cache.pop(device_id, None)

    discovery_signatures = getattr(client, "_discovery_signature", None)
    if isinstance(discovery_signatures, dict):
        discovery_signatures.pop(device_id, None)


def install_firmware_runtime() -> None:
    """Install dynamic NOAH/NEXA firmware composition after the HA runtime hooks."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = ha_client_module.Client

    original_publish_input_register = client_cls.publish_input_register

    def publish_input_register_with_firmware(self, state):
        if _supports_combined_firmware(state.device_id):
            config = getattr(self, "_config_cache", {}).get(state.device_id)
            datalogger_version = getattr(config, "sw_version", None) if config else None
            firmware_version = compose_combined_firmware(
                state.payload,
                datalogger_version,
            )
            if firmware_version:
                firmware_cache = getattr(self, "_composed_firmware_cache", None)
                if firmware_cache is None:
                    firmware_cache = {}
                    self._composed_firmware_cache = firmware_cache

                if firmware_cache.get(state.device_id) != firmware_version:
                    firmware_cache[state.device_id] = firmware_version
                    _invalidate_discovery_for_firmware_change(self, state.device_id)

                payload = dict(state.payload)
                payload["fw_version"] = firmware_version
                state = HomeAssistantInputRegister(
                    device_id=state.device_id,
                    payload=payload,
                )

        return original_publish_input_register(self, state)

    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_with_firmware(self, device_id: str, *args, **kwargs):
        if not _supports_combined_firmware(device_id):
            return original_publish_discovery(self, device_id, *args, **kwargs)

        mqtt_publish = self._client.publish
        discovery_topic = f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"
        firmware_version = getattr(self, "_composed_firmware_cache", {}).get(device_id)

        def publish(topic, payload=None, *publish_args, **publish_kwargs):
            if topic == discovery_topic and payload:
                payload = _rewrite_firmware_discovery(
                    device_id,
                    payload,
                    firmware_version,
                )
            return mqtt_publish(topic, payload, *publish_args, **publish_kwargs)

        self._client.publish = publish
        try:
            return original_publish_discovery(self, device_id, *args, **kwargs)
        finally:
            self._client.publish = mqtt_publish

    client_cls.publish_input_register = publish_input_register_with_firmware
    client_cls._Client__publish_device_discovery = publish_discovery_with_firmware

    _INSTALLED = True
    LOG.info("Installed NOAH/NEXA ShinePhone-style firmware composition")
