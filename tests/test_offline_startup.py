"""Real Paho lifecycle while a local broker is unavailable at startup."""
import socket
import threading

import pytest

from grobro import grobro, ha, model


@pytest.mark.parametrize("client_type", [ha.Client, grobro.Client])
def test_offline_broker_does_not_prevent_startup_and_shutdown(tmp_path, monkeypatch, client_type):
    monkeypatch.chdir(tmp_path)
    # Reserve a port without listening: connections fail, and no other process
    # can accidentally supply a broker on the selected address during this test.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        config = model.MQTTConfig(host="127.0.0.1", port=reservation.getsockname()[1])
        target = client_type(config) if client_type is ha.Client else client_type(config, config)
        failed = threading.Event()
        failure_callback = target._client.on_connect_fail
        def on_failure(*args):
            failure_callback(*args)
            failed.set()
        target._client.on_connect_fail = on_failure
        try:
            target.start()
            assert failed.wait(4), "Paho did not attempt the initial connection"
            assert not target._client.is_connected()
        finally:
            target.stop()
        assert target._client._thread is None
