"""Home Assistant client extension for combined NOAH/NEXA firmware versions.

Growatt exposes device firmware in ``fw_version_part_*`` input registers and
the datalogger firmware as ``DeviceConfig.sw_version``. ShinePhone presents
those values as one version. Examples::

    NOAH: 19.19.14 + 4.0.1.9 -> 19.19.14.4019
    NEXA: 14.12.14.11 + 4.0.1.9 -> 14.12.14.11.4019

Only values actually received from the device are used. In particular, no
additional NEXA component such as ``9000`` is synthesized when it is not
available as a decoded field.

This module keeps the existing entity IDs and device metadata fields while
presenting the same combined version in Home Assistant.
"""

from __future__ import annotations

import json

from grobro.model.growatt_registers import HomeAssistantInputRegister

from .client import Client as _BaseClient
from .client import HA_BASE_TOPIC

_COMBINED_FIRMWARE_PREFIXES = ("0PVP", "0HVR")


def _firmware_part_names(payload: dict) -> list[str]:
    """Return firmware part keys in numeric part order."""
    names = [name for name in payload if name.startswith("fw_version_part_")]

    def part_number(name: str) -> int:
        try:
            return int(name.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            return 9999

    return sorted(names, key=part_number)


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


def compose_combined_firmware(payload: dict, datalogger_version: object) -> str | None:
    """Build a ShinePhone-style firmware version from received values."""
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
    return f"{base_version}.{suffix}" if suffix else base_version


# Backwards-compatible name for callers/tests that used the first implementation.
compose_noah_firmware = compose_combined_firmware


class Client(_BaseClient):
    """GroBro HA client with ShinePhone-style NOAH/NEXA firmware presentation."""

    def publish_input_register(self, state: HomeAssistantInputRegister):
        if state.device_id.startswith(_COMBINED_FIRMWARE_PREFIXES):
            config = getattr(self, "_config_cache", {}).get(state.device_id)
            datalogger_version = getattr(config, "sw_version", None) if config else None
            firmware_version = compose_combined_firmware(
                state.payload,
                datalogger_version,
            )

            if firmware_version:
                versions = getattr(self, "_combined_firmware_versions", None)
                if versions is None:
                    versions = {}
                    self._combined_firmware_versions = versions

                if versions.get(state.device_id) != firmware_version:
                    versions[state.device_id] = firmware_version
                    # Device metadata is part of MQTT discovery, so force a new
                    # discovery payload whenever the combined version changes.
                    self._discovery_payload_cache.pop(state.device_id, None)

                payload = dict(state.payload)
                payload["fw_version"] = firmware_version
                state = HomeAssistantInputRegister(
                    device_id=state.device_id,
                    payload=payload,
                )

        return super().publish_input_register(state)

    def _Client__publish_device_discovery(
        self,
        device_id: str,
        effective_max_bat: int | None = None,
    ):
        """Rewrite only NOAH/NEXA firmware fields in generated discovery."""
        if not device_id.startswith(_COMBINED_FIRMWARE_PREFIXES):
            return _BaseClient._Client__publish_device_discovery(
                self,
                device_id,
                effective_max_bat,
            )

        original_publish = self._client.publish
        discovery_topic = f"{HA_BASE_TOPIC}/device/{device_id}/config"

        def publish(topic, payload=None, *args, **kwargs):
            if topic == discovery_topic and payload:
                try:
                    data = json.loads(payload)
                    version = getattr(
                        self,
                        "_combined_firmware_versions",
                        {},
                    ).get(device_id)

                    if version:
                        device = data.get("dev")
                        if isinstance(device, dict):
                            device["sw_version"] = version

                    components = data.get("cmps")
                    if isinstance(components, dict):
                        firmware = components.get(f"grobro_{device_id}_fw_version")
                        if isinstance(firmware, dict):
                            firmware["value_template"] = (
                                "{{ value_json['fw_version'] }}"
                            )

                    payload = json.dumps(
                        data,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    pass

            return original_publish(topic, payload, *args, **kwargs)

        self._client.publish = publish
        try:
            return _BaseClient._Client__publish_device_discovery(
                self,
                device_id,
                effective_max_bat,
            )
        finally:
            self._client.publish = original_publish
