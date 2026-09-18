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

    def test_logger_fallback_on_bad_level(self):
        import grobro.ha_bridge as mod

        with patch.dict(
            "os.environ",
            {"LOG_LEVEL": "INVALID_LEVEL_THAT_IS_WAY_TOO_LONG"},
        ):
            with patch.object(mod.logging, "basicConfig") as mock_basic_config:
                mock_basic_config.side_effect = [ValueError("bad level"), None]
                mod.configure_logging()
                assert mock_basic_config.call_count == 2

    def test_logger_fallback_prints_error(self, capsys):
        import grobro.ha_bridge as mod

        with patch.dict("os.environ", {"LOG_LEVEL": "INVALID"}):
            with patch.object(mod.logging, "basicConfig") as mock_basic_config:
                mock_basic_config.side_effect = [ValueError("bad level"), None]
                mod.configure_logging()
                captured = capsys.readouterr()
                assert "Failed to setup logger" in captured.out

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
