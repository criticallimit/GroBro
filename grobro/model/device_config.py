import json
import logging
import os
from typing import Optional

from pydantic import BaseModel

LOG = logging.getLogger(__name__)


class DeviceConfig(BaseModel):
    data_interval: Optional[str] = None
    unknown_5: Optional[str] = None
    unknown_6: Optional[str] = None
    password: Optional[str] = None
    serial_number: Optional[str] = None
    protocol_version: Optional[str] = None
    unknown_10: Optional[str] = None
    unknown_11: Optional[str] = None
    dns_address: Optional[str] = None
    device_type: Optional[str] = None
    local_ip: Optional[str] = None
    unknown_port: Optional[str] = None
    mac_address: Optional[str] = None
    remote_ip: Optional[str] = None
    remote_port: Optional[str] = None
    remote_url: Optional[str] = None
    model_id: Optional[str] = None
    sw_version: Optional[str] = None
    hw_version: Optional[str] = None
    unknown_23: Optional[str] = None
    unknown_24: Optional[str] = None
    subnet_mask: Optional[str] = None
    default_gateway: Optional[str] = None
    unknown_27: Optional[str] = None
    unknown_28: Optional[str] = None
    unknown_29: Optional[str] = None
    timezone: Optional[str] = None
    datetime: Optional[str] = None
    wifi_signal: Optional[str] = None
    raw: Optional[str] = None

    @property
    def device_id(self) -> Optional[str]:
        return self.serial_number

    def to_file(self, file_path: str) -> None:
        # Password and raw fallback payloads are useful while processing a live
        # packet but are not required to restore HA discovery after restart.
        # Avoid persisting them to disk even in the add-on's private /data area.
        persisted = self.model_dump_json(
            exclude_none=True,
            exclude={"password", "raw"},
        )

        directory = os.path.dirname(os.path.abspath(file_path)) or "."
        os.makedirs(directory, exist_ok=True)
        temp_path = f"{file_path}.tmp"

        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(persisted)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                # Some container/filesystem combinations may not support chmod.
                pass
            # Atomic replacement prevents a restart/power-loss during a write
            # from leaving a truncated config_<device>.json behind.
            os.replace(temp_path, file_path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass

    @staticmethod
    def from_file(file_path: str) -> Optional["DeviceConfig"]:
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            # Do not log the full config: it may contain credentials left by an
            # older GroBro version. Log only the source path at DEBUG level.
            LOG.debug("Loaded device config from %s", file_path)
            return DeviceConfig(**data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            LOG.error("Failed to load config %s: %s", file_path, exc)
            return None
