"""NOAH firmware composition for Home Assistant.

Growatt exposes the NOAH storage firmware in three input-register parts while
its datalogger firmware is already available as ``DeviceConfig.sw_version``.
ShinePhone displays both as one version, for example::

    19.19.14 + 4.0.1.9 -> 19.19.14.4019

This runtime layer keeps the existing Home Assistant ``Firmware Version``
entity and changes only its value. No firmware value is hard-coded.
"""

from __future__ import annotations

import json
import logging

import grobro.model as model
from grobro.ha import client as ha_client_module
from grobro.model.growatt_registers import HomeAssistantInputRegister

LOG = logging.getLogger(__name__)
_INSTALLED = False


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


def compose_noah_firmware(payload: dict, datalogger_version: object) -> str | None:
    """Build the ShinePhone-style NOAH firmware version from live values."""
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


def _rewrite_firmware_discovery(device_id: str, payload: object) -> object:
    """Point the existing Firmware Version sensor at the composed state field."""
    if not payload or not isinstance(payload, (str, bytes, bytearray)):
        return payload

    try:
        raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
        data = json.loads(raw)
    except (UnicodeDecodeError, TypeError, ValueError):
        return payload

    components = data.get("cmps")
    if not isinstance(components, dict):
        return payload

    component = components.get(f"grobro_{device_id}_fw_version")
    if not isinstance(component, dict):
        return payload

    component["value_template"] = "{{ value_json['fw_version'] }}"
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def install_firmware_runtime() -> None:
    """Install dynamic NOAH firmware composition after the HA runtime hooks."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = ha_client_module.Client

    original_publish_input_register = client_cls.publish_input_register

    def publish_input_register_with_firmware(self, state):
        if model.is_family(state.device_id, "noah"):
            config = getattr(self, "_config_cache", {}).get(state.device_id)
            datalogger_version = getattr(config, "sw_version", None) if config else None
            firmware_version = compose_noah_firmware(
                state.payload,
                datalogger_version,
            )
            if firmware_version:
                payload = dict(state.payload)
                payload["fw_version"] = firmware_version
                state = HomeAssistantInputRegister(
                    device_id=state.device_id,
                    payload=payload,
                )

        return original_publish_input_register(self, state)

    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_with_firmware(self, device_id: str, *args, **kwargs):
        if not model.is_family(device_id, "noah"):
            return original_publish_discovery(self, device_id, *args, **kwargs)

        mqtt_publish = self._client.publish
        discovery_topic = f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"

        def publish(topic, payload=None, *publish_args, **publish_kwargs):
            if topic == discovery_topic and payload:
                payload = _rewrite_firmware_discovery(device_id, payload)
            return mqtt_publish(topic, payload, *publish_args, **publish_kwargs)

        self._client.publish = publish
        try:
            return original_publish_discovery(self, device_id, *args, **kwargs)
        finally:
            self._client.publish = mqtt_publish

    client_cls.publish_input_register = publish_input_register_with_firmware
    client_cls._Client__publish_device_discovery = publish_discovery_with_firmware

    _INSTALLED = True
    LOG.info("Installed NOAH ShinePhone-style firmware composition")
