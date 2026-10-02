import logging
from typing import Optional
import os
from pydantic import BaseModel

LOG = logging.getLogger(__name__)


def subscription_rejected(reason_codes) -> bool:
    """Recognize MQTT 3 failure codes and Paho MQTT 5 ReasonCode objects."""
    return any(
        getattr(reason, "is_failure", False) is True
        or (isinstance(reason, int) and reason >= 128)
        for reason in reason_codes
    )


def publish_succeeded(result) -> bool:
    """Whether Paho accepted a publish locally (not a delivery guarantee)."""
    status = getattr(result, "rc", None)
    if status is None and isinstance(result, (list, tuple)) and result:
        status = result[0]
    # Legacy callbacks return None; real Paho error codes are integers.
    return not isinstance(status, int) or status == 0

class MQTTConfig(BaseModel):
    host: str
    port: int
    use_tls: bool = False
    username: Optional[str] = None
    password: Optional[str] = None

    @staticmethod
    def from_env(prefix: str, defaults: "MQTTConfig") -> "MQTTConfig":
        host = os.getenv(f"{prefix}_MQTT_HOST", defaults.host)
        port = int(os.getenv(f"{prefix}_MQTT_PORT", defaults.port))
        use_tls = os.getenv(f"{prefix}_MQTT_TLS", str(defaults.use_tls)).lower() == "true"
        username = os.getenv(f"{prefix}_MQTT_USER", defaults.username)
        password = os.getenv(f"{prefix}_MQTT_PASS", defaults.password)

        LOG.info(f"Loading MQTT configuration from environment (prefix: {prefix})")
        LOG.info(f"MQTT Host: {'***:' if password else ''}{username if username else 'anonymous'}@{host}:{port} (TLS: {use_tls})")

        return MQTTConfig(
            host=host,
            port=port,
            use_tls=use_tls,
            username=username,
            password=password,
        )
