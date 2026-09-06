import grobro.model as model


def test_device_family_helpers_are_exposed_from_model_package():
    assert model.is_known_device("0PVPTEST") is True
    assert model.is_gateway("RAQTEST") is True
    assert model.get_device_type_name("QMNTEST") == "NEO"
    assert model.get_known_registers("UNKNOWN") is None
