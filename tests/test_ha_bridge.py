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
