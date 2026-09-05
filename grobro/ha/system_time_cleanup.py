"""Hide the legacy System Time Home Assistant entity.

Register 31 remains part of the active register maps because GroBro uses it for
automatic clock synchronization. Only the Home Assistant discovery component is
removed; protocol support and scheduled writes are unchanged.
"""

from __future__ import annotations

from grobro.ha import cleanup as ha_cleanup

_INSTALLED = False


def install_system_time_entity_cleanup() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_clean = ha_cleanup._clean_discovery_payload

    def clean_without_system_time(client, device_id: str, data: dict) -> dict:
        data = original_clean(client, device_id, data)
        components = data.get("cmps")
        if isinstance(components, dict):
            components.pop(f"grobro_{device_id}_cmd_system_time", None)
        return data

    ha_cleanup._clean_discovery_payload = clean_without_system_time
    _INSTALLED = True
