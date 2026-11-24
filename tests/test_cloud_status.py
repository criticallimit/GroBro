"""Cloud status is based on real MQTT callbacks, not connection attempts."""
from unittest.mock import patch

from grobro.grobro import cloud_status


def test_cloud_indicator_connection_and_traffic():
    cloud_status.clear()
    assert cloud_status.snapshot(enabled=False)["status"] == "disabled"
    cloud_status.connecting("noah")
    assert cloud_status.snapshot(enabled=True)["status"] == "disconnected"
    cloud_status.connected("noah")
    assert cloud_status.snapshot(enabled=True)["status"] == "connected"
    cloud_status.sent()
    cloud_status.received()
    status = cloud_status.snapshot(enabled=True)
    assert status["tx"] is True
    assert status["rx"] is True
    cloud_status.connecting("neo")
    assert cloud_status.snapshot(enabled=True)["status"] == "partial"
    cloud_status.connected("neo")
    assert cloud_status.snapshot(enabled=True)["status"] == "connected"
    cloud_status.disconnected("noah")
    assert cloud_status.snapshot(enabled=True)["status"] == "partial"
    cloud_status.disconnected("neo")
    assert cloud_status.snapshot(enabled=True)["status"] == "disconnected"
    assert cloud_status.snapshot(enabled=True)["tx"] is False
    assert cloud_status.snapshot(enabled=True)["rx"] is False
    cloud_status.clear()


def test_led_activity_expires_without_new_packets():
    cloud_status.clear()
    cloud_status.connected("noah")
    with patch("grobro.grobro.cloud_status.time.monotonic", side_effect=[100.0, 100.0]):
        cloud_status.sent()
        cloud_status.received()
    with patch("grobro.grobro.cloud_status.time.monotonic", return_value=103.0):
        state = cloud_status.snapshot(enabled=True)
    assert state["status"] == "connected"
    assert state["tx"] is False
    assert state["rx"] is False
    cloud_status.clear()
