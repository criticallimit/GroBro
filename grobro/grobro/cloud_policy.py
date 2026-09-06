"""Growatt cloud forwarding policy parsing and decisions.

This module keeps environment parsing and allow/deny decisions out of the MQTT
client so cloud forwarding behaviour has one focused, testable source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass

_FALSE_VALUES = {"", "false", "0", "no", "off"}


@dataclass(frozen=True, slots=True)
class CloudForwardingPolicy:
    """Resolved Growatt cloud forwarding settings."""

    enabled: bool
    allowlist: frozenset[str]
    block_config_commands: bool = False

    @classmethod
    def parse(
        cls,
        cloud_value: str | None,
        config_filter_value: str | None = None,
    ) -> "CloudForwardingPolicy":
        raw = (cloud_value or "false").strip()
        lowered = raw.lower()

        if lowered in _FALSE_VALUES:
            enabled = False
            allowlist: frozenset[str] = frozenset()
        elif lowered == "true":
            enabled = True
            allowlist = frozenset()
        else:
            enabled = True
            allowlist = frozenset(
                item.strip() for item in raw.split(",") if item.strip()
            )

        block_config = (config_filter_value or "false").strip().lower() == "true"
        return cls(
            enabled=enabled,
            allowlist=allowlist,
            block_config_commands=block_config,
        )

    @property
    def forwards_all_devices(self) -> bool:
        """Return whether forwarding is enabled without a device allowlist."""
        return self.enabled and not self.allowlist

    def allows_device(self, device_id: str) -> bool:
        """Return whether traffic for this device may use Growatt cloud."""
        if not self.enabled:
            return False
        return not self.allowlist or device_id in self.allowlist

    def should_block_cloud_message(self, message_type: int) -> bool:
        """Return whether one Cloud -> device message must be filtered."""
        return self.block_config_commands and message_type in (0x0118, 0x0110)
