"""Normalize NOAH/NEXA MAC addresses for Home Assistant device metadata.

Growatt exposes the datalogger MAC address through FE19/TLV config key 16.
The base HA client already publishes a valid colon-separated address as a
Home Assistant device connection. This runtime layer additionally accepts
other common complete representations (hyphenated, compact, dotted),
normalizes them, and deliberately rejects masked/incomplete values.
"""

from __future__ import annotations

import logging

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False
_TARGET_PREFIXES = ("0PVP", "0HVR")


def normalize_mac_address(value: object) -> str | None:
    """Return a canonical lower-case MAC address or ``None`` if invalid."""
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    compact = text.replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12 or any(ch not in "0123456789abcdef" for ch in compact):
        return None

    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def install_mac_runtime() -> None:
    """Install robust MAC handling for NOAH/NEXA HA device discovery."""
    global _INSTALLED
    if _INSTALLED:
        return

    client_cls = ha_client_module.Client
    original_device_info = client_cls._Client__device_info_from_config

    def device_info_with_normalized_mac(self, device_id: str):
        device_info = original_device_info(self, device_id)

        if device_id.startswith(_TARGET_PREFIXES):
            config = getattr(self, "_config_cache", {}).get(device_id)
            mac = normalize_mac_address(getattr(config, "mac_address", None) if config else None)
            if mac:
                device_info["connections"] = [["mac", mac]]

        return device_info

    client_cls._Client__device_info_from_config = device_info_with_normalized_mac
    _INSTALLED = True
    LOG.info("Installed normalized NOAH/NEXA MAC device-info handling")
