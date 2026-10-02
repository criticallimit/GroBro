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


def _plain_noah_status(heater_value: int, msg_type: int = 0x0104) -> bytes:
    payload = bytearray(noah_heater._NOAH_HEATER_ABSOLUTE_OFFSET + 1)
    payload[6:8] = msg_type.to_bytes(2, "big")
    payload[noah_heater._NOAH_HEATER_ABSOLUTE_OFFSET] = heater_value
    return bytes(payload)


def test_noah_heater_decodes_unscrambled_status_packet():
    assert (
        noah_heater.heater_state_from_unscrambled(
            _plain_noah_status(3),
            "0PVPTEST",
        )
        == "1&2 On"
    )


def test_noah_heater_rejects_wrong_family_type_and_value():
    assert noah_heater.heater_state_from_unscrambled(_plain_noah_status(1), "QMNTEST") is None
    assert noah_heater.heater_state_from_unscrambled(_plain_noah_status(1, 0x0103), "0PVPTEST") is None
    assert noah_heater.heater_state_from_unscrambled(_plain_noah_status(16), "0PVPTEST") is None


def test_noah_heater_hook_is_compatibility_noop():
    assert noah_heater.install_noah_heater_hook() is None
