from types import SimpleNamespace

from grobro.grobro import noah_heater, raw_dump


def test_raw_dump_hook_is_idempotent(monkeypatch):
    original = raw_dump.grobro_client_module.dump_message_binary
    monkeypatch.setattr(raw_dump, "_INSTALLED", False)
    try:
        raw_dump.install_raw_dump_hook()
        first = raw_dump.grobro_client_module.dump_message_binary
        raw_dump.install_raw_dump_hook()
        second = raw_dump.grobro_client_module.dump_message_binary

        assert first is raw_dump.dump_message_binary_compat
        assert second is first
    finally:
        raw_dump.grobro_client_module.dump_message_binary = original


def test_noah_heater_hook_restores_input_callback(monkeypatch):
    client_cls = noah_heater.grobro_client_module.Client
    original_on_message = client_cls._Client__on_message
    monkeypatch.setattr(noah_heater, "_INSTALLED", False)

    captured = []

    def fake_on_message(self, client, userdata, msg):
        state = SimpleNamespace(device_id="0PVPTEST", payload={})
        self.on_input_register(state)
        captured.append(state.payload.copy())

    client_cls._Client__on_message = fake_on_message
    monkeypatch.setattr(
        noah_heater,
        "heater_state_from_packet",
        lambda payload, device_id: "1 On",
    )

    try:
        noah_heater.install_noah_heater_hook()
        instance = object.__new__(client_cls)
        original_callback = lambda state: None
        instance.on_input_register = original_callback
        msg = SimpleNamespace(topic="c/33/0PVPTEST", payload=b"payload")

        client_cls._Client__on_message(instance, None, None, msg)

        assert captured == [{"heater": "1 On"}]
        assert instance.on_input_register is original_callback
    finally:
        client_cls._Client__on_message = original_on_message
