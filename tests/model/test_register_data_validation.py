from grobro.model.growatt_registers import (
    GrowattRegisterDataType,
    GrowattRegisterDataTypes,
)


def test_numeric_register_decoder_rejects_unsupported_lengths():
    decoder = GrowattRegisterDataType(data_type=GrowattRegisterDataTypes.INT)
    assert decoder.parse(b"\x00\x01\x02") is None
    assert decoder.parse(None) is None


def test_time_decoder_rejects_invalid_hhmm_values():
    decoder = GrowattRegisterDataType(data_type=GrowattRegisterDataTypes.TIME_HHMM)
    assert decoder.parse(b"\x17\x3b") == "23:59"
    assert decoder.parse(b"\x18\x00") is None
    assert decoder.parse(b"\x17\x3c") is None


def test_signed_numeric_decoder_still_parses_valid_values():
    decoder = GrowattRegisterDataType(data_type=GrowattRegisterDataTypes.SIGNED_INT)
    assert decoder.parse(b"\xff\xff") == -1
