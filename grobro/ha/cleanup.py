"""Small compatibility/cleanup layer for the Home Assistant bridge.

Keeps upstream GroBro behavior intact while correcting a few legacy behaviors:
- battery count fallback prefers the explicit bat_cnt input register and never
  assumes four batteries when no evidence is present;
- the existing Device SN entity keeps the same name/unique id but publishes the
  configured serial number when available instead of blindly mirroring device_id;
- a legacy sw_version publish that accidentally used the device id is corrected;
- MQTT discovery origin metadata points to this debug fork.

Stable Home Assistant entity names, unique ids and device identifiers are
preserved so existing automations and dashboards continue to work.
"""

from __future__ import annotations

import json
import logging

from grobro.ha import client as ha_client_module

LOG = logging.getLogger(__name__)
_INSTALLED = False
FORK_URL = "https://github.com/criticallimit/GroBro"


def _detect_bat_count(payload: dict) -> int:
    """Resolve battery count from telemetry with a conservative fallback."""
    bat_cnt = payload.get("bat_cnt")
    if isinstance(bat_cnt, int) and 1 <= bat_cnt <= 4:
        return bat_cnt

    count = 1
    for bat_num in range(2, 5):
        key = f"bat{bat_num}_ser_part_1"
        value = payload.get(key)
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def _configured_serial(client, device_id: str) -> str:
    """Return the best available serial while keeping device_id as fallback."""
    config = client._config_cache.get(device_id)
    serial = getattr(config, "serial_number", None) if config else None
    if serial and str(serial).strip():
        return str(serial).strip()
    return device_id


def install_ha_cleanup_hook() -> None:
    """Install narrowly scoped fixes without changing HA entity identities."""
    global _INSTALLED
    if _INSTALLED:
        return

    ha_client_module._detect_bat_count = _detect_bat_count

    client_cls = ha_client_module.Client
    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_clean(self, device_id: str, effective_max_bat=None):
        original_publish = self._client.publish

        def publish(topic, payload=None, *args, **kwargs):
            if (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/device/{device_id}/config"
                and payload
            ):
                try:
                    data = json.loads(payload)
                    origin = data.get("o")
                    if isinstance(origin, dict):
                        origin["url"] = FORK_URL
                    payload = json.dumps(
                        data,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                except (TypeError, ValueError):
                    pass

            # Keep the existing Device SN entity/topic/unique id exactly as-is,
            # but feed it from the configured serial number when available.
            if topic == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/serial":
                payload = _configured_serial(self, device_id)

            if (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/sw_version"
            ):
                config = self._config_cache.get(device_id)
                sw_version = getattr(config, "sw_version", None) if config else None
                if not sw_version:
                    return None
                payload = sw_version

            return original_publish(topic, payload, *args, **kwargs)

        self._client.publish = publish
        try:
            return original_publish_discovery(
                self,
                device_id,
                effective_max_bat,
            )
        finally:
            self._client.publish = original_publish

    client_cls._Client__publish_device_discovery = publish_discovery_clean
    _INSTALLED = True
    LOG.info("Installed GroBro Home Assistant cleanup compatibility layer")
