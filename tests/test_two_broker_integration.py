"""Live two-broker smoke test for Better GroBro's connected MQTT transports.

Requires independent local Mosquitto brokers supplied by the existing CI job
(E2E_MQTT_PORT=1883 and E2E_MQTT_TARGET_PORT=1884). This is separate from
mock-only callback tests and must never target production Growatt endpoints.
"""

import os
import socket
import time

import pytest

from grobro.ha_bridge import wire_clients
from grobro.model.mqtt_config import MQTTConfig


def _wait_until(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def _local_broker_available(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


@pytest.mark.integration
def test_source_subscription_and_ha_connection_use_independent_real_brokers(tmp_path, monkeypatch):
    from grobro.grobro.client import Client as SourceClient
    from grobro.ha.client import Client as TargetClient

    host = os.environ.get("E2E_MQTT_HOST", "127.0.0.1")
    source_port = int(os.environ.get("E2E_MQTT_PORT", "1883"))
    target_port = int(os.environ.get("E2E_MQTT_TARGET_PORT", "1884"))

    # No external broker access: test exclusively local addresses.
    if host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("integration tests must use local test brokers")
    if source_port == target_port:
        pytest.skip("two distinct broker ports are required")
    if not all(_local_broker_available(host, p) for p in (source_port, target_port)):
        pytest.skip("local source and target brokers are not running")

    monkeypatch.chdir(tmp_path)
    source_cfg = MQTTConfig(host=host, port=source_port)
    target_cfg = MQTTConfig(host=host, port=target_port)
    target = TargetClient(target_cfg)
    source = SourceClient(source_cfg, source_cfg)
    wire_clients(target, source)

    try:
        target.start()
        source.start()
        assert _wait_until(lambda: source.config_reads_ready()), (
            "source never received successful c/# subscription acknowledgment"
        )
        assert _wait_until(lambda: target._ha_mqtt_connected), (
            "target never completed MQTT CONNACK"
        )

        # Removing the SOURCE connection must not turn off the HA transport.
        source._client.disconnect()
        assert _wait_until(lambda: not source.config_reads_ready())
        assert target._ha_mqtt_connected is True
    finally:
        try:
            source.stop()
        finally:
            target.stop()
