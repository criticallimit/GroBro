from unittest.mock import patch


class TestSignalHandler:
    @patch("grobro.grobro.signals.signal.signal")
    def test_init(self, mock_signal):
        from grobro.ha_bridge import SignalHandler

        sh = SignalHandler()
        assert sh.caught is True
        assert sh._stop_event.is_set() is False

    @patch("grobro.grobro.signals.signal.signal")
    def test_handle_signal(self, mock_signal):
        from grobro.ha_bridge import SignalHandler

        sh = SignalHandler()
        sh._handle(None, None)
        assert sh._stop_event.is_set() is True
        assert sh.caught is False

    @patch("grobro.grobro.signals.signal.signal")
    def test_wait_blocks_on_stop_event(self, mock_signal):
        from grobro.ha_bridge import SignalHandler

        sh = SignalHandler()
        with patch.object(sh._stop_event, "wait") as mock_wait:
            sh.wait()
        mock_wait.assert_called_once_with()


class TestModule:
    def test_has_configs(self):
        import grobro.ha_bridge

        assert hasattr(grobro.ha_bridge, "GROBRO_MQTT_CONFIG")
        assert hasattr(grobro.ha_bridge, "HA_MQTT_CONFIG")
        assert hasattr(grobro.ha_bridge, "FORWARD_MQTT_CONFIG")

    def test_logger_forces_selected_level_even_with_existing_handlers(self):
        import grobro.ha_bridge as mod

        with patch.dict("os.environ", {"LOG_LEVEL": "INFO"}):
            with patch.object(mod.logging, "basicConfig") as mock_basic_config:
                with patch.object(mod.logging.getLogger(), "setLevel") as mock_set_level:
                    level, _logger = mod.configure_logging()

        assert level == "INFO"
        mock_basic_config.assert_called_once_with(
            level=mod.logging.INFO,
            format=mod._LOG_FORMAT,
            force=True,
        )
        mock_set_level.assert_called_once_with(mod.logging.INFO)

    def test_logger_invalid_level_falls_back_to_error(self, capsys):
        import grobro.ha_bridge as mod

        with patch.dict("os.environ", {"LOG_LEVEL": "INVALID"}):
            with patch.object(mod.logging, "basicConfig") as mock_basic_config:
                with patch.object(mod.logging.getLogger(), "setLevel") as mock_set_level:
                    level, _logger = mod.configure_logging()

        captured = capsys.readouterr()
        assert "Invalid LOG_LEVEL" in captured.out
        assert level == "ERROR"
        mock_basic_config.assert_called_once_with(
            level=mod.logging.ERROR,
            format=mod._LOG_FORMAT,
            force=True,
        )
        mock_set_level.assert_called_once_with(mod.logging.ERROR)

    def test_config_from_env_source_prefix(self):
        from grobro.ha_bridge import load_bridge_mqtt_configs

        with patch.dict(
            "os.environ",
            {
                "SOURCE_MQTT_HOST": "source.local",
                "SOURCE_MQTT_PORT": "1883",
                "TARGET_MQTT_HOST": "target.local",
                "TARGET_MQTT_PORT": "2883",
            },
        ):
            source, target, _forward = load_bridge_mqtt_configs()
            assert source.host == "source.local"
            assert source.port == 1883
            assert target.host == "target.local"
            assert target.port == 2883


def test_run_clients_logs_successful_startup():
    import grobro.ha_bridge as mod

    class FakeClient:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    class FakeSignal:
        def wait(self):
            return None

    ha_client = FakeClient()
    grobro_client = FakeClient()

    with patch.object(mod.LOG, "info") as log_info:
        mod.run_clients(ha_client, grobro_client, FakeSignal())

    assert ha_client.started is True
    assert grobro_client.started is True
    assert ha_client.stopped is True
    assert grobro_client.stopped is True
    log_info.assert_any_call("Better GroBro started successfully")


def test_bridge_client_lifecycle_failure_matrix():
    """A failure in either startup path must attempt cleanup of both clients."""
    import pytest
    import grobro.ha_bridge as mod

    for failing_stage in ("ha_start", "source_start", "signal_wait", "ha_stop"):
        events = []

        class FakeClient:
            def __init__(self, label):
                self.label = label

            def start(self):
                events.append(f"{self.label}_start")
                if failing_stage == f"{self.label}_start":
                    raise RuntimeError(failing_stage)

            def stop(self):
                events.append(f"{self.label}_stop")
                if failing_stage == f"{self.label}_stop":
                    raise RuntimeError(failing_stage)

        class FakeSignal:
            def wait(self):
                events.append("signal_wait")
                if failing_stage == "signal_wait":
                    raise RuntimeError("signal_wait")

        with pytest.raises(RuntimeError, match=failing_stage):
            mod.run_clients(FakeClient("ha"), FakeClient("source"), FakeSignal())

        assert events[0] == "ha_start"
        assert events[-2:] == ["ha_stop", "source_stop"]
        if failing_stage == "ha_start":
            assert "source_start" not in events
        else:
            assert events.index("ha_start") < events.index("source_start")
        if failing_stage in ("ha_start", "source_start"):
            assert "signal_wait" not in events


def test_bridge_wiring_connects_all_data_command_and_readiness_callbacks():
    """Verify the central source-to-target contract, independent of device family."""
    from types import SimpleNamespace
    from grobro.ha_bridge import wire_clients

    callback_names = (
        "publish_input_register",
        "publish_holding_register_input",
        "set_config",
        "set_derived_config",
        "handle_config_read_response",
        "publish_config_register_value",
        "publish_smart_meter",
        "handle_source_ready",
    )
    command_names = ("send_command", "send_config_read_message", "config_reads_ready")
    ha = SimpleNamespace(**{name: object() for name in callback_names})
    source = SimpleNamespace(**{name: object() for name in command_names})
    source.send_config_message = lambda *args: args

    wire_clients(ha, source)

    mappings = {
        "on_input_register": "publish_input_register",
        "on_holding_register_input": "publish_holding_register_input",
        "on_config": "set_config",
        "on_derived_config": "set_derived_config",
        "on_config_read_response": "handle_config_read_response",
        "on_config_register_value": "publish_config_register_value",
        "on_smart_meter": "publish_smart_meter",
        "on_ready": "handle_source_ready",
    }
    for target_name, source_name in mappings.items():
        assert getattr(source, target_name) is getattr(ha, source_name)
    assert ha.on_command is source.send_command
    assert ha.on_config_read is source.send_config_read_message
    assert ha.config_reads_ready is source.config_reads_ready
    assert ha.on_config_command("device", 76, "value") == ("device", 76, "value")
