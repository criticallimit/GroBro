"""Small compatibility/cleanup layer for the Home Assistant bridge.

Keeps upstream GroBro behavior intact while correcting a few legacy behaviors:
- battery count fallback prefers the explicit bat_cnt input register and never
  assumes four batteries when no evidence is present;
- a legacy sw_version publish that accidentally used the device id is corrected;
- MQTT discovery origin metadata points to this debug fork.

Existing Home Assistant entity names, unique IDs and device identifiers are kept
unchanged so existing dashboards and automations continue to work.
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

    # NOAH battery 1 is represented by the MQTT/device id. Additional battery
    # serials start at bat2_* in the current register map.
    count = 1
    for bat_num in range(2, 5):
        key = f"bat{bat_num}_ser_part_1"
        value = payload.get(key)
        if value is not None and str(value).strip("\x00 "):
            count = bat_num
    return count


def install_ha_cleanup_hook() -> None:
    """Install narrowly scoped fixes without changing HA entity identities."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Replace only the helper used by _resolve_max_bat.
    ha_client_module._detect_bat_count = _detect_bat_count

    client_cls = ha_client_module.Client
    original_publish_discovery = client_cls._Client__publish_device_discovery

    def publish_discovery_clean(self, device_id: str, effective_max_bat=None):
        original_publish = self._client.publish

        def publish(topic, payload=None, *args, **kwargs):
            # Keep all existing entities and unique IDs unchanged. Only update
            # the discovery origin URL so Home Assistant points to this fork.
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

            # Older GroBro code publishes device_id to the sw_version state
            # topic when discovery is unchanged. Replace it with the actual
            # configured software version, or suppress the bogus value.
            if (
                topic
                == f"{ha_client_module.HA_BASE_TOPIC}/grobro/{device_id}/sw_version"
            ):
                config = self._config_cache.get(device_id)
                sw_version = (
                    getattr(config, "sw_version", None) if config else None
                )
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
